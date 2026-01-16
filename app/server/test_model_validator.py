# 数据验证模块
from pathlib import Path
from typing import Dict, List, Any
from sqlalchemy import text
import logging

logger = logging.getLogger("test_model")

class DataValidator:
    """数据验证器"""
    
    def __init__(self, config: dict):
        self.config = config
        self.settings = self._resolve_settings()
    
    def _resolve_settings(self):
        """获取数据库设置"""
        from app.server.config.settings import ServerSettings
        from app.server.test_model import _resolved_settings
        return _resolved_settings()
    
    def validate_config(self) -> Dict[str, Any]:
        """验证配置的有效性"""
        errors = []
        warnings = []
        
        # 验证长度范围
        length_range = self.config.get("length_range", [1000, 6000])
        if not isinstance(length_range, list) or len(length_range) != 2:
            errors.append("长度范围格式错误")
        elif length_range[0] >= length_range[1]:
            errors.append(f"长度范围无效: {length_range}")
        elif length_range[0] < 100 or length_range[1] > 20000:
            warnings.append(f"长度范围可能不合理: {length_range}")
        
        # 验证宽度范围
        width_range = self.config.get("width_range", [800, 2000])
        if not isinstance(width_range, list) or len(width_range) != 2:
            errors.append("宽度范围格式错误")
        elif width_range[0] >= width_range[1]:
            errors.append(f"宽度范围无效: {width_range}")
        
        # 验证厚度范围
        thickness_range = self.config.get("thickness_range", [5, 50])
        if not isinstance(thickness_range, list) or len(thickness_range) != 2:
            errors.append("厚度范围格式错误")
        elif thickness_range[0] >= thickness_range[1]:
            errors.append(f"厚度范围无效: {thickness_range}")
        
        # 验证缺陷间隔
        defect_interval = self.config.get("defect_interval_seconds", 3)
        if defect_interval < 1:
            errors.append(f"缺陷间隔过短: {defect_interval}")
        
        # 验证每间隔缺陷数
        defects_per_interval = self.config.get("defects_per_interval", 5)
        if defects_per_interval < 0:
            errors.append(f"每间隔缺陷数不能为负: {defects_per_interval}")
        elif defects_per_interval > 50:
            warnings.append(f"每间隔缺陷数可能过多: {defects_per_interval}")
        
        # 验证记录间隔
        record_interval = self.config.get("record_interval_seconds", 5)
        if record_interval < 1:
            errors.append(f"记录间隔过短: {record_interval}")
        
        # 验证图像数量范围
        image_count_min = self.config.get("image_count_min", 8)
        image_count_max = self.config.get("image_count_max", 20)
        if image_count_min >= image_count_max:
            errors.append(f"图像数量范围无效: [{image_count_min}, {image_count_max}]")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
    
    def validate_sequence_data(self, seq_no: int) -> Dict[str, Any]:
        """验证单个序列的数据完整性"""
        issues = []
        
        try:
            # 1. 验证钢材记录
            main_session = self._get_main_session()
            try:
                steel_record = main_session.execute(
                    text(f"SELECT * FROM steelrecord WHERE SeqNo = {seq_no}")
                ).fetchone()
                
                if not steel_record:
                    issues.append("钢材记录不存在")
                else:
                    # 验证钢材规格
                    if steel_record["SteelLen"] <= 0 or steel_record["SteelLen"] > 20000:
                        issues.append(f"钢材长度异常: {steel_record['SteelLen']}")
                    if steel_record["Width"] <= 0 or steel_record["Width"] > 3000:
                        issues.append(f"钢材宽度异常: {steel_record['Width']}")
                    if steel_record["Thick"] <= 0 or steel_record["Thick"] > 100:
                        issues.append(f"钢材厚度异常: {steel_record['Thick']}")
                    
                    # 验证缺陷数量一致性
                    defect_session = self._get_defect_session()
                    try:
                        top_count = defect_session.execute(
                            text(f"SELECT COUNT(*) FROM camdefect1 WHERE seqNo = {seq_no}")
                        ).scalar() or 0
                        bottom_count = defect_session.execute(
                            text(f"SELECT COUNT(*) FROM camdefect2 WHERE seqNo = {seq_no}")
                        ).scalar() or 0
                        total_defects = top_count + bottom_count
                        
                        if steel_record["DefectNum"] != total_defects:
                            issues.append(f"缺陷数量不匹配: 记录={steel_record['DefectNum']}, 实际={total_defects}")
                        
                        # 验证缺陷分布
                        if total_defects > 0:
                            top_avg = top_count / (top_count + bottom_count) if (top_count + bottom_count) > 0 else 0
                            if top_avg > 0.8 or top_avg < 0.2:
                                issues.append(f"缺陷分布不均衡: 上表面={top_count}, 下表面={bottom_count}")
                        
                    finally:
                        defect_session.close()
                        
            finally:
                main_session.close()
            
            # 2. 验证图像文件
            from app.server.test_model import _image_roots
            top_root, bottom_root = _image_roots(self.config)
            
            for surface, root in [("top", top_root), ("bottom", bottom_root)]:
                seq_dir = root / str(seq_no)
                if not seq_dir.exists():
                    issues.append(f"{surface} 表面图像目录不存在")
                    continue
                
                # 检查图像文件
                image_files = list(seq_dir.rglob("*.jpg"))
                if len(image_files) == 0:
                    issues.append(f"{surface} 表面没有图像文件")
                else:
                    # 验证图像索引连续性
                    indices = sorted(set(int(f.stem) for f in image_files if f.stem.isdigit()))
                    if indices:
                        # 检查索引是否从1开始
                        if indices[0] != 1:
                            issues.append(f"{surface} 表面图像索引不从1开始: {indices[0]}")
                        
                        # 检查是否有缺失索引
                        if len(indices) > 1:
                            expected_indices = set(range(1, max(indices) + 1))
                            missing_indices = expected_indices - set(indices)
                            if missing_indices:
                                issues.append(f"{surface} 表面缺失图像索引: {sorted(missing_indices)[:10]}...")
            
            # 3. 验证record.json
            for root in [top_root, bottom_root]:
                seq_dir = root / str(seq_no)
                record_file = seq_dir / "record.json"
                if record_file.exists():
                    import json
                    try:
                        record_data = json.loads(record_file.read_text(encoding='utf-8'))
                        
                        if record_data.get("seq_no") != seq_no:
                            issues.append(f"record.json中的序列号不匹配: {record_data.get('seq_no')} vs {seq_no}")
                        
                        image_count = record_data.get("image_count", 0)
                        if image_count <= 0:
                            issues.append(f"record.json中的图像数量无效: {image_count}")
                        
                        # 验证图像文件数量与record.json一致
                        actual_image_count = len(image_files)
                        if actual_image_count != image_count:
                            issues.append(f"图像文件数量与record.json不一致: {actual_image_count} vs {image_count}")
                            
                    except json.JSONDecodeError:
                        issues.append("record.json格式错误")
                    except Exception as e:
                        issues.append(f"record.json读取错误: {str(e)}")
                
        except Exception as e:
            issues.append(f"验证过程中发生异常: {str(e)}")
            logger.exception("Data validation failed")
        
        return {
            "seq_no": seq_no,
            "valid": len(issues) == 0,
            "issues": issues,
            "issue_count": len(issues),
        }
    
    def _get_main_session(self):
        """获取主数据库会话"""
        from app.server.database import get_main_session
        return get_main_session(self.settings)
    
    def _get_defect_session(self):
        """获取缺陷数据库会话"""
        from app.server.database import get_defect_session
        return get_defect_session(self.settings)
    
    def validate_system_integrity(self) -> Dict[str, Any]:
        """验证系统整体数据完整性"""
        issues = []
        stats = {}
        
        try:
            main_session = self._get_main_session()
            defect_session = self._get_defect_session()
            
            try:
                # 统计数据库记录数
                steel_count = main_session.execute(
                    text("SELECT COUNT(*) FROM steelrecord")
                ).scalar() or 0
                
                top_defect_count = defect_session.execute(
                    text("SELECT COUNT(*) FROM camdefect1")
                ).scalar() or 0
                
                bottom_defect_count = defect_session.execute(
                    text("SELECT COUNT(*) FROM camdefect2")
                ).scalar() or 0
                
                # 检查序列号连续性
                seq_list = main_session.execute(
                    text("SELECT SeqNo FROM steelrecord ORDER BY SeqNo")
                ).fetchall()
                
                if seq_list:
                    seq_numbers = [row[0] for row in seq_list]
                    # 检查是否有重复序列号
                    if len(seq_numbers) != len(set(seq_numbers)):
                        issues.append("存在重复的序列号")
                    
                    # 检查序列号间隔是否过大
                    for i in range(1, len(seq_numbers)):
                        gap = seq_numbers[i] - seq_numbers[i-1]
                        if gap > 10:
                            issues.append(f"序列号{seq_numbers[i-1]}和{seq_numbers[i]}之间间隔过大: {gap}")
                
                stats = {
                    "steel_count": steel_count,
                    "top_defect_count": top_defect_count,
                    "bottom_defect_count": bottom_defect_count,
                    "total_defect_count": top_defect_count + bottom_defect_count,
                    "avg_defects_per_steel": (top_defect_count + bottom_defect_count) / steel_count if steel_count > 0 else 0,
                }
                
                # 验证文件系统
                from app.server.test_model import _image_roots
                top_root, bottom_root = _image_roots(self.config)
                
                for surface, root in [("top", top_root), ("bottom", bottom_root)]:
                    if not root.exists():
                        issues.append(f"{surface} 表面根目录不存在")
                        continue
                    
                    # 检查目录结构
                    seq_dirs = [d for d in root.iterdir() if d.is_dir() and d.stem.isdigit()]
                    if len(seq_dirs) != steel_count:
                        issues.append(f"{surface} 表面目录数量与钢材记录不匹配: {len(seq_dirs)} vs {steel_count}")
                
            finally:
                main_session.close()
                defect_session.close()
                
        except Exception as e:
            issues.append(f"系统完整性验证异常: {str(e)}")
            logger.exception("System integrity validation failed")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "stats": stats,
            "issue_count": len(issues),
        }


def validate_config(config: dict) -> Dict[str, Any]:
    """验证配置的便捷函数"""
    validator = DataValidator(config)
    return validator.validate_config()


def validate_sequence(seq_no: int, config: dict) -> Dict[str, Any]:
    """验证序列数据的便捷函数"""
    validator = DataValidator(config)
    return validator.validate_sequence_data(seq_no)


def validate_system(config: dict) -> Dict[str, Any]:
    """验证系统完整性的便捷函数"""
    validator = DataValidator(config)
    return validator.validate_system_integrity()
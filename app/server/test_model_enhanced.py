# 数据真实性增强模块
import random
import math
from typing import Dict, Tuple

class DefectClassConfig:
    """缺陷类别配置"""
    def __init__(self):
        self.defect_classes = {
            1: {"name": "划痕", "size_range": (20, 50), "frequency": 0.3},
            2: {"name": "辊印", "size_range": (30, 80), "frequency": 0.2},
            3: {"name": "头尾", "size_range": (50, 150), "frequency": 0.15},
            4: {"name": "氧化铁皮", "size_range": (40, 100), "frequency": 0.1},
            5: {"name": "异物压入", "size_range": (30, 70), "frequency": 0.1},
            6: {"name": "周期性缺陷", "size_range": (80, 200), "frequency": 0.05},
            7: {"name": "油渍", "size_range": (40, 80), "frequency": 0.08},
            8: {"name": "气泡", "size_range": (25, 60), "frequency": 0.05},
            9: {"name": "结疤", "size_range": (35, 75), "frequency": 0.07},
            10: {"name": "折叠", "size_range": (45, 90), "frequency": 0.06},
        }

class SteelSpecConfig:
    """钢材规格配置"""
    def __init__(self):
        # 真实的钢材规格范围（单位：mm）
        self.length_ranges = {
            "hot_rolled": (2000, 8000),  # 热轧
            "cold_rolled": (3000, 12000),  # 冷轧
            "plate": (1000, 6000),  # 钢板
        }
        self.width_ranges = {
            "standard": (800, 2000),
            "wide": (1500, 3000),
            "narrow": (500, 1000),
        }
        self.thickness_ranges = {
            "thin": (2, 10),
            "medium": (10, 30),
            "thick": (30, 80),
        }

class RealisticDataGenerator:
    """真实数据生成器"""
    
    def __init__(self):
        self.defect_config = DefectClassConfig()
        self.steel_config = SteelSpecConfig()
    
    def generate_steel_spec(self, use_realistic: bool = True) -> Dict:
        """生成真实钢材规格"""
        if not use_realistic:
            return self._generate_random_spec()
        
        # 真实的钢材规格分布
        length_type = random.choices(
            list(self.steel_config.length_ranges.keys()),
            weights=[0.6, 0.3, 0.1]  # 热轧最常见
        )[0]
        width_type = random.choices(
            list(self.steel_config.width_ranges.keys()),
            weights=[0.7, 0.2, 0.1]  # 标准宽度最常见
        )[0]
        thickness_type = random.choices(
            list(self.steel_config.thickness_ranges.keys()),
            weights=[0.5, 0.35, 0.15]  # 中等厚度最常见
        )[0]
        
        length_range = self.steel_config.length_ranges[length_type]
        width_range = self.steel_config.width_ranges[width_type]
        thickness_range = self.steel_config.thickness_ranges[thickness_type]
        
        return {
            "length": random.randint(*length_range),
            "width": random.randint(*width_range),
            "thickness": random.randint(*thickness_range),
            "type": length_type,
            "width_type": width_type,
            "thickness_type": thickness_type,
        }
    
    def _generate_random_spec(self) -> Dict:
        """生成随机钢材规格"""
        return {
            "length": random.randint(1000, 6000),
            "width": random.randint(800, 2000),
            "thickness": random.randint(5, 50),
        }
    
    def generate_defect_distribution(self, frame_width: int, frame_height: int) -> Dict[int, int]:
        """生成真实的缺陷分布"""
        total_pixels = frame_width * frame_height
        
        # 基于缺陷类别频率生成预期数量
        expected_defects = {}
        for class_id, config in self.defect_config.defect_classes.items():
            # 缺陷数量与频率成正比
            base_count = int(total_pixels * config["frequency"] / 1000000)
            # 添加随机波动
            actual_count = max(0, int(base_count * random.uniform(0.5, 1.5)))
            expected_defects[class_id] = actual_count
        
        return expected_defects
    
    def generate_realistic_defect_size(self, class_id: int, scale: float = 1.0) -> Tuple[int, int]:
        """生成真实的缺陷大小"""
        defect_class = self.defect_config.defect_classes.get(class_id, {})
        size_range = defect_class.get("size_range", (50, 100))
        
        # 根据缩放调整大小
        base_width = random.randint(*size_range)
        base_height = random.randint(*size_range)
        
        # 缩放调整
        width = int(base_width * scale)
        height = int(base_height * scale)
        
        # 确保缺陷在合理范围内
        width = max(20, min(width, 500))
        height = max(20, min(height, 500))
        
        return width, height
    
    def generate_defect_pattern(self, seq_no: int) -> Dict:
        """生成缺陷分布模式"""
        # 基于序列号生成一些分布模式
        pattern_type = seq_no % 3  # 三种模式循环
        
        patterns = {
            0: {"name": "随机分布", "description": "缺陷随机分布"},
            1: {"name": "聚集分布", "description": "缺陷倾向于聚集在特定区域"},
            2: {"name": "均匀分布", "description": "缺陷均匀分布"},
        }
        
        base_pattern = patterns[pattern_type]
        
        # 添加一些随机变化
        if random.random() < 0.3:
            pattern_type = random.choice([0, 1, 2])
        
        final_pattern = patterns[pattern_type]
        
        return {
            "pattern_type": pattern_type,
            "pattern_name": final_pattern["name"],
            "description": final_pattern["description"],
            "seq_no": seq_no,
        }

    def calculate_defect_density(self, seq_no: int, defect_count: int) -> float:
        """计算缺陷密度（缺陷数/图像面积）"""
        frame_area = 16384 * 1024  # 标准帧面积
        density = defect_count / frame_area
        return density
    
    def validate_defect_count(self, count: int, seq_no: int) -> Tuple[bool, str]:
        """验证缺陷数量是否合理"""
        # 基于历史统计和钢材规格验证
        density = self.calculate_defect_density(seq_no, count)
        
        # 真实的缺陷密度范围（每平方毫米的缺陷数）
        reasonable_density_range = (0.001, 0.05)
        
        if density < reasonable_density_range[0]:
            return False, f"缺陷密度过低: {density:.6f} < {reasonable_density_range[0]:.6f}"
        elif density > reasonable_density_range[1]:
            return False, f"缺陷密度过高: {density:.6f} > {reasonable_density_range[1]:.6f}"
        else:
            return True, "缺陷数量合理"
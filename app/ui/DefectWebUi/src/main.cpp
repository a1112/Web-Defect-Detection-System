#include <QCoreApplication>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QObject>
#include <QString>
#include <QUrl>

class FrameBridge : public QObject {
    Q_OBJECT
    Q_PROPERTY(QUrl sourceUrl READ sourceUrl WRITE setSourceUrl NOTIFY sourceUrlChanged FINAL)

public:
    explicit FrameBridge(QObject *parent = nullptr)
        : QObject(parent) {}

    QUrl sourceUrl() const { return m_sourceUrl; }

    void setSourceUrl(const QUrl &url) {
        if (url == m_sourceUrl) {
            return;
        }
        m_sourceUrl = url;
        emit sourceUrlChanged();
    }

    Q_INVOKABLE void loadFromString(const QString &urlString) {
        const QUrl candidate(urlString);
        if (!candidate.isValid()) {
            return;
        }
        setSourceUrl(candidate);
    }

    Q_INVOKABLE void useSample() {
        setSourceUrl(QUrl(QStringLiteral("qrc:/resources/images/placeholder.png")));
    }

signals:
    void sourceUrlChanged();

private:
    QUrl m_sourceUrl;
};

int main(int argc, char *argv[]) {
    QGuiApplication app(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("DefectWeb"));
    QCoreApplication::setOrganizationDomain(QStringLiteral("example.local"));
    QCoreApplication::setApplicationName(QStringLiteral("Defect Web UI"));

    FrameBridge frameBridge;
    frameBridge.useSample();

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("frameBridge"), &frameBridge);

    const QUrl url(QStringLiteral("qrc:/qt/qml/DefectWebUi/main.qml"));
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreated, &app,
                     [url](QObject *obj, const QUrl &objUrl) {
                         if (!obj && url == objUrl)
                             QCoreApplication::exit(-1);
                     },
                     Qt::QueuedConnection);

    engine.load(url);
    if (engine.rootObjects().isEmpty()) {
        return -1;
    }

    return app.exec();
}

#include "main.moc"

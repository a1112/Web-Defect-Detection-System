#include <QCoreApplication>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QObject>
#include <QUrl>

int main(int argc, char *argv[]) {
    QGuiApplication app(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("DefectWeb"));
    QCoreApplication::setOrganizationDomain(QStringLiteral("example.local"));
    QCoreApplication::setApplicationName(QStringLiteral("Defect Web UI"));

    QQmlApplicationEngine engine;
    const QUrl url(QStringLiteral("qrc:/qml/App.qml"));
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

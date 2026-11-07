import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: root
    width: 770; height: 760
    visible: true
    title: "AMCL · Qt Quick 对比演示"
    color: "#18252e"
    property string resultText: "采样中…前 2 秒预热；可以点击卡片试手感。"
    Text {
        x: 12; y: 12
        text: "Qt Quick · 整页实时透明度\n120 张资源卡片 / 1.8 秒往返淡入淡出"
        color: "#e3edf3"; font.pixelSize: 17; font.bold: true
    }
    Text {
        x: 12; y: 65; width: parent.width - 24; height: 44
        text: root.resultText; color: "#e3edf3"; font.pixelSize: 13
        wrapMode: Text.Wrap
    }
    Rectangle {
        y: 99; width: 60; height: 4; radius: 2; color: "#61d4c2"
        SequentialAnimation on x {
            loops: Animation.Infinite
            NumberAnimation { from: 12; to: 612; duration: 900 }
            NumberAnimation { from: 612; to: 12; duration: 900 }
        }
    }
    Grid {
        id: page
        x: 12; y: 116; width: parent.width - 24; height: parent.height - y - 12
        columns: 6; spacing: 5
        Repeater {
            model: 120
            Rectangle {
                id: card
                required property int index
                width: (page.width - 25) / 6
                height: (page.height - 95) / 20
                radius: 5
                color: mouse.pressed ? "#244451" : mouse.containsMouse ? "#406778" : "#304b59"
                border.color: "#52717e"
                Text {
                    anchors.centerIn: parent
                    text: "Resource " + String(card.index + 1).padStart(3, "0")
                    horizontalAlignment: Text.AlignHCenter
                    color: "#e3edf3"; font.pixelSize: 13
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent; hoverEnabled: true
                    onClicked: root.resultText = "收到点击：Resource " + (card.index+1)
                }
            }
        }
        SequentialAnimation on opacity {
            loops: Animation.Infinite
            NumberAnimation { from: 0.45; to: 1.0; duration: 900 }
            NumberAnimation { from: 1.0; to: 0.45; duration: 900 }
        }
    }
}

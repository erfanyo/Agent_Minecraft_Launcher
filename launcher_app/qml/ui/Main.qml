import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: rootShell
    width: 1220
    height: 790
    minimumWidth: 820
    minimumHeight: 620
    visible: true
    title: "AMCL · Agent Minecraft Launcher"
    property var bridge: amclBridge
    color: themeColors.bg

    QtObject {
        id: themeColors
        readonly property color bg: rootShell.bridge.colorToken("bg1", rootShell.bridge.resolvedTheme)
        readonly property color surface: rootShell.bridge.colorToken("panel_bg", rootShell.bridge.resolvedTheme)
        readonly property color raised: rootShell.bridge.colorToken("bg2", rootShell.bridge.resolvedTheme)
        readonly property color line: rootShell.bridge.colorToken("border_soft", rootShell.bridge.resolvedTheme)
        readonly property color ink: rootShell.bridge.colorToken("text0", rootShell.bridge.resolvedTheme)
        readonly property color muted: rootShell.bridge.colorToken("text1", rootShell.bridge.resolvedTheme)
        readonly property color accent: rootShell.bridge.colorToken("accent", rootShell.bridge.resolvedTheme)
        readonly property color green: rootShell.bridge.colorToken("success", rootShell.bridge.resolvedTheme)
        readonly property color warn: rootShell.bridge.colorToken("warning", rootShell.bridge.resolvedTheme)
    }
    property int pageIndex: 0
    property string pageName: "Home"

    component Surface: Rectangle {
        color: themeColors.surface
        radius: 18
        border.width: 1
        border.color: themeColors.line
    }
    component NavItem: Item {
        required property string label
        required property string glyph
        required property int target
        property bool active: pageIndex === target
        signal chosen(int page)
        implicitHeight: 46
        Rectangle {
            anchors.fill: parent
            radius: 12
            color: parent.active ? (rootShell.bridge.resolvedTheme === "light" ? "#eaf1ff" : "#2b3b55") : "transparent"
            Behavior on color { ColorAnimation { duration: 150 } }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 13; anchors.rightMargin: 12
            spacing: 12
            Text { text: parent.parent.glyph; color: parent.parent.active ? themeColors.accent : themeColors.muted; font.pixelSize: 17; Layout.preferredWidth: 20; horizontalAlignment: Text.AlignHCenter }
            Text { text: parent.parent.label; color: parent.parent.active ? themeColors.ink : themeColors.muted; font.pixelSize: 14; font.weight: parent.parent.active ? Font.DemiBold : Font.Normal; Layout.fillWidth: true; elide: Text.ElideRight }
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.chosen(parent.target) }
    }
    function go(index, label) { pageIndex = index; pageName = label }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.preferredWidth: 226
            Layout.fillHeight: true
            color: themeColors.surface
            border.color: themeColors.line
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 0
                RowLayout {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 26
                    Rectangle {
                        width: 40; height: 40; radius: 13
                        gradient: Gradient { GradientStop { position: 0; color: themeColors.accent } GradientStop { position: 1; color: themeColors.green } }
                        Text { anchors.centerIn: parent; text: "A"; color: "white"; font.pixelSize: 21; font.bold: true }
                    }
                    ColumnLayout {
                        spacing: 1
                        Text { text: "AMCL"; color: themeColors.ink; font.pixelSize: 16; font.bold: true }
                        Text { text: "MINECRAFT LAUNCHER"; color: themeColors.muted; font.pixelSize: 8; font.letterSpacing: 1.1 }
                    }
                }
                Text { text: "PLAY"; color: themeColors.muted; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.4; Layout.leftMargin: 10; Layout.bottomMargin: 8 }
                NavItem { label: "Home"; glyph: "⌂"; target: 0; Layout.fillWidth: true; onChosen: go(page, "Home") }
                NavItem { label: "Instances"; glyph: "▦"; target: 1; Layout.fillWidth: true; onChosen: go(page, "Instances") }
                NavItem { label: "Resources"; glyph: "✣"; target: 2; Layout.fillWidth: true; onChosen: go(page, "Resources") }
                Item { Layout.preferredHeight: 22 }
                Text { text: "WORKSPACE"; color: themeColors.muted; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.4; Layout.leftMargin: 10; Layout.bottomMargin: 8 }
                NavItem { label: "Agent workbench"; glyph: "✳"; target: 3; Layout.fillWidth: true; onChosen: go(page, "Agent workbench") }
                Item { Layout.fillHeight: true }
                Surface {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 105
                    color: themeColors.raised
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 13; spacing: 6
                        Text { text: "YOUR WORLD, YOUR WAY"; color: themeColors.accent; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.1 }
                        Text { text: "One place for your\nMinecraft instances."; color: themeColors.ink; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }
                }
                NavItem { label: "Settings"; glyph: "⚙"; target: 4; Layout.fillWidth: true; Layout.topMargin: 12; onChosen: go(page, "Settings") }
                Text { text: "Experimental Qt Quick shell"; color: themeColors.muted; font.pixelSize: 9; Layout.leftMargin: 10; Layout.topMargin: 7; Layout.bottomMargin: 2 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 66; color: themeColors.bg
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 30; anchors.rightMargin: 30
                    Text { text: "Workspace  /  " + pageName; color: themeColors.muted; font.pixelSize: 12 }
                    Item { Layout.fillWidth: true }
                    Rectangle { width: 9; height: 9; radius: 5; color: rootShell.bridge.busy ? themeColors.warn : themeColors.green }
                    Text { text: rootShell.bridge.busy ? "Task running" : "Ready"; color: themeColors.muted; font.pixelSize: 11 }
                    Rectangle {
                        Layout.preferredWidth: 38; Layout.preferredHeight: 38; radius: 12; color: themeColors.surface; border.color: themeColors.line
                        Text { anchors.centerIn: parent; text: "?"; color: themeColors.muted; font.pixelSize: 14 }
                        ToolTip.visible: helpMouse.containsMouse
                        ToolTip.text: "AMCL Qt Quick experiment. Existing Widgets UI remains available via main.py."
                        MouseArea { id: helpMouse; anchors.fill: parent; hoverEnabled: true }
                    }
                }
            }
            Item {
                id: pageHost
                Layout.fillWidth: true; Layout.fillHeight: true
                Loader {
                    id: pageLoader
                    anchors.fill: parent
                    anchors.leftMargin: 30; anchors.rightMargin: 30; anchors.bottomMargin: 24
                    sourceComponent: [homePage, instancesPage, resourcesPage, agentPage, settingsPage][pageIndex]
                    opacity: 1
                    onSourceComponentChanged: {
                        opacity = 0.2
                        fade.restart()
                    }
                    NumberAnimation { id: fade; target: pageLoader; property: "opacity"; from: 0.2; to: 1; duration: 170; easing.type: Easing.OutCubic }
                }
            }
        }
    }

    Component {
        id: homePage
        Flickable {
            contentWidth: width; contentHeight: homeContent.implicitHeight
            clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            ColumnLayout {
                id: homeContent
                width: parent.width; spacing: 19
                RowLayout {
                    Layout.fillWidth: true; Layout.topMargin: 6
                    ColumnLayout {
                        spacing: 5
                        Text { text: "Make room for adventure."; color: themeColors.ink; font.pixelSize: 30; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: "Your worlds, packs and next steps — all in one place."; color: themeColors.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                    Item { Layout.fillWidth: true }
                    Button { text: "View instances  →"; onClicked: go(1, "Instances"); contentItem: Text { text: parent.text; color: "white"; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } background: Rectangle { color: themeColors.accent; radius: 11 } }
                }
                Surface {
                    Layout.fillWidth: true; Layout.preferredHeight: 236; clip: true
                    Rectangle {
                        anchors.fill: parent; radius: 18
                        gradient: Gradient { GradientStop { position: 0; color: rootShell.bridge.resolvedTheme === "light" ? "#e8f1ff" : "#243950" } GradientStop { position: 0.52; color: rootShell.bridge.resolvedTheme === "light" ? "#e4f3ef" : "#23403f" } GradientStop { position: 1; color: themeColors.surface } }
                    }
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 28; spacing: 24
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 10
                            Text { text: "PICK UP WHERE YOU LEFT OFF"; color: themeColors.accent; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.25 }
                            Text { text: rootShell.bridge.selectedInstance.length ? rootShell.bridge.selectedInstance : "Your next world starts here"; color: themeColors.ink; font.pixelSize: 25; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Text { text: rootShell.bridge.selectedInstance.length ? "Your instance is selected. AMCL can check its local launch setup before you start." : "No local instances found yet. Add or install one to get going."; color: themeColors.muted; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            RowLayout {
                                Layout.topMargin: 6; spacing: 10
                                Button {
                                    visible: !rootShell.bridge.launchReady
                                    enabled: !rootShell.bridge.busy && rootShell.bridge.selectedInstance.length > 0
                                    text: rootShell.bridge.busy ? "Preparing…" : "Prepare to play  →"
                                    onClicked: rootShell.bridge.prepareLaunch()
                                    contentItem: Text { text: parent.text; color: "white"; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    background: Rectangle { radius: 11; color: parent.enabled ? themeColors.accent : themeColors.muted; opacity: parent.down ? 0.8 : 1; Behavior on opacity { NumberAnimation { duration: 100 } } }
                                }
                                Button {
                                    visible: rootShell.bridge.launchReady
                                    text: "Start game  ▶"
                                    onClicked: rootShell.bridge.launchPrepared()
                                    contentItem: Text { text: parent.text; color: "white"; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    background: Rectangle { radius: 11; color: themeColors.green }
                                }
                                Button { visible: rootShell.bridge.busy; text: "Cancel"; onClicked: rootShell.bridge.cancelTask(); flat: true; contentItem: Text { text: parent.text; color: themeColors.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
                                Button { text: "Browse instances"; onClicked: go(1, "Instances"); flat: true; contentItem: Text { text: parent.text; color: themeColors.accent; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
                            }
                        }
                        Rectangle {
                            visible: pageLoader.width >= 800
                            Layout.preferredWidth: 170; Layout.preferredHeight: 170; radius: 28; color: rootShell.bridge.resolvedTheme === "light" ? "#ffffff90" : "#10182080"; border.color: themeColors.line
                            Column {
                                anchors.centerIn: parent; spacing: 3
                                Text { text: "▧"; color: themeColors.green; font.pixelSize: 66; anchors.horizontalCenter: parent.horizontalCenter }
                                Text { text: "WORLD READY"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.5; anchors.horizontalCenter: parent.horizontalCenter }
                            }
                        }
                    }
                }
                Surface {
                    Layout.fillWidth: true; Layout.preferredHeight: rootShell.bridge.busy || rootShell.bridge.launchReady ? 112 : 94
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 17; spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            Rectangle { width: 8; height: 8; radius: 4; color: rootShell.bridge.busy ? themeColors.warn : rootShell.bridge.launchReady ? themeColors.green : themeColors.accent }
                            Text { text: rootShell.bridge.busy ? "WORK IN PROGRESS" : rootShell.bridge.launchReady ? "READY FOR YOU" : "WHAT'S NEXT"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.1 }
                            Item { Layout.fillWidth: true }
                            Text { text: rootShell.bridge.busy ? Math.round(rootShell.bridge.progress * 100) + "%" : "Details"; color: themeColors.muted; font.pixelSize: 10 }
                        }
                        Text { text: rootShell.bridge.status; color: themeColors.ink; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 2; elide: Text.ElideRight }
                        ProgressBar { visible: rootShell.bridge.busy; Layout.fillWidth: true; value: rootShell.bridge.progress; background: Rectangle { implicitHeight: 4; radius: 2; color: themeColors.line } contentItem: Item { Rectangle { width: parent.width * parent.parent.visualPosition; height: 4; radius: 2; color: themeColors.accent } } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 13
                    Surface {
                        Layout.fillWidth: true; Layout.preferredHeight: 128
                        ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 7
                            Text { text: "INSTANCES"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.1 }
                            RowLayout { Text { text: rootShell.bridge.instanceModel.rowCount(); color: themeColors.ink; font.pixelSize: 26; font.bold: true } Text { text: "local worlds"; color: themeColors.muted; font.pixelSize: 12 } Item { Layout.fillWidth: true } }
                            Text { text: "Manage versions, loaders and profiles"; color: themeColors.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                    Surface {
                        Layout.fillWidth: true; Layout.preferredHeight: 128
                        ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 7
                            Text { text: "AGENT WORKBENCH"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.1 }
                            Text { text: "A clearer path from goal to game."; color: themeColors.ink; font.pixelSize: 14; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Text { text: "This experiment connects local launch tasks; AI file edits and review are not wired into QML yet."; color: themeColors.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: instancesPage
        ColumnLayout {
            spacing: 16
            RowLayout {
                Layout.fillWidth: true; Layout.topMargin: 6
                ColumnLayout { spacing: 4
                    Text { text: "Your instances"; color: themeColors.ink; font.pixelSize: 26; font.bold: true }
                    Text { text: "Choose a world. We’ll keep the Java and launch details out of your way."; color: themeColors.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                }
                Item { Layout.fillWidth: true }
                Button { text: "↻  Refresh"; onClicked: rootShell.bridge.refreshInstances(); flat: true; contentItem: Text { text: parent.text; color: themeColors.accent; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
            }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 15
                Surface {
                    Layout.preferredWidth: pageLoader.width < 700 ? 175 : pageLoader.width < 900 ? 230 : 310; Layout.fillHeight: true; clip: true
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 12; spacing: 8
                        RowLayout { Layout.fillWidth: true; Text { text: rootShell.bridge.instanceModel.rowCount() + " instances"; color: themeColors.muted; font.pixelSize: 11 } Item { Layout.fillWidth: true } }
                        ListView {
                            id: instanceList
                            Layout.fillWidth: true; Layout.fillHeight: true; model: rootShell.bridge.instanceModel; clip: true; spacing: 6
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            delegate: Rectangle {
                                required property string instanceId
                                required property string loader
                                required property string baseVersion
                                required property bool running
                                required property int index
                                width: ListView.view.width; height: 71; radius: 12
                                color: rootShell.bridge.selectedInstance === instanceId ? (rootShell.bridge.resolvedTheme === "light" ? "#eaf1ff" : "#2b3b55") : instanceHover.containsMouse ? themeColors.raised : "transparent"
                                Behavior on color { ColorAnimation { duration: 130 } }
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 11; spacing: 11
                                    Rectangle { width: 39; height: 39; radius: 12; color: rootShell.bridge.resolvedTheme === "light" ? "#dce9fb" : "#35495e"; Text { anchors.centerIn: parent; text: "▦"; color: themeColors.accent; font.pixelSize: 18 } }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 4
                                        Text { text: instanceId; color: themeColors.ink; font.pixelSize: 12; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                                        Text { text: loader + "  ·  " + baseVersion; color: themeColors.muted; font.pixelSize: 10; elide: Text.ElideRight; Layout.fillWidth: true }
                                    }
                                    Text { visible: running; text: "●"; color: themeColors.green; font.pixelSize: 9 }
                                }
                                MouseArea { id: instanceHover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rootShell.bridge.selectInstance(instanceId) }
                            }
                            Label { anchors.centerIn: parent; visible: rootShell.bridge.instanceModel.rowCount() === 0; text: "No instances found.\nExisting folders are scanned automatically.\n\nTo install or import one, open the full launcher with python main.py."; color: themeColors.muted; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; width: parent.width * 0.84 }
                        }
                    }
                }
                Surface {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 23; spacing: 15
                        RowLayout { Layout.fillWidth: true
                            Rectangle { width: 45; height: 45; radius: 14; color: rootShell.bridge.resolvedTheme === "light" ? "#eaf1ff" : "#2b3b55"; Text { anchors.centerIn: parent; text: "▦"; color: themeColors.accent; font.pixelSize: 22 } }
                            ColumnLayout { Layout.fillWidth: true; spacing: 3
                                Text { text: rootShell.bridge.selectedInstance || "Select an instance"; color: themeColors.ink; font.pixelSize: 20; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Text { text: rootShell.bridge.selectedInstance.length ? "Selected workspace" : "Choose an instance from the list"; color: themeColors.muted; font.pixelSize: 11 }
                            }
                            Button { visible: pageLoader.width >= 680; text: "Prepare launch"; enabled: !rootShell.bridge.busy && rootShell.bridge.selectedInstance.length > 0; onClicked: rootShell.bridge.prepareLaunch(); contentItem: Text { text: parent.text; color: "white"; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } background: Rectangle { color: parent.enabled ? themeColors.accent : themeColors.muted; radius: 10 } }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: themeColors.line }
                        Text { text: "READY CHECK"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.1 }
                        RowLayout { Layout.fillWidth: true; spacing: 10
                            Rectangle { width: 28; height: 28; radius: 9; color: rootShell.bridge.launchReady ? "#183f35" : themeColors.raised; Text { anchors.centerIn: parent; text: rootShell.bridge.launchReady ? "✓" : "1"; color: rootShell.bridge.launchReady ? themeColors.green : themeColors.muted } }
                            ColumnLayout { Layout.fillWidth: true; spacing: 2; Text { text: "Check local files and Java"; color: themeColors.ink; font.pixelSize: 12; font.bold: true } Text { text: "AMCL prepares a launch plan before starting anything."; color: themeColors.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true } }
                        }
                        RowLayout { Layout.fillWidth: true; spacing: 10
                            Rectangle { width: 28; height: 28; radius: 9; color: rootShell.bridge.launchReady ? "#183f35" : themeColors.raised; Text { anchors.centerIn: parent; text: rootShell.bridge.launchReady ? "✓" : "2"; color: rootShell.bridge.launchReady ? themeColors.green : themeColors.muted } }
                            ColumnLayout { Layout.fillWidth: true; spacing: 2; Text { text: "You decide when to start"; color: themeColors.ink; font.pixelSize: 12; font.bold: true } Text { text: "No game process starts until you press Start game."; color: themeColors.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true } }
                        }
                        Surface { id: taskSurface; Layout.fillWidth: true; Layout.fillHeight: true; color: themeColors.raised
                            Text { id: taskHeading; anchors.left: parent.left; anchors.top: parent.top; anchors.leftMargin: 15; anchors.topMargin: 15; text: "TASK STATUS"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.1 }
                            Text { id: taskMessage; anchors.left: parent.left; anchors.right: parent.right; anchors.top: taskHeading.bottom; anchors.leftMargin: 15; anchors.rightMargin: 15; anchors.topMargin: 12; text: rootShell.bridge.status; color: themeColors.ink; font.pixelSize: 12; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight }
                            ProgressBar { anchors.left: parent.left; anchors.right: parent.right; anchors.top: taskMessage.bottom; anchors.leftMargin: 15; anchors.rightMargin: 15; anchors.topMargin: 10; visible: rootShell.bridge.busy; value: rootShell.bridge.progress }
                            RowLayout { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 12; height: 38; Item { Layout.fillWidth: true } Button { visible: rootShell.bridge.busy; text: "Cancel"; onClicked: rootShell.bridge.cancelTask() } Button { visible: rootShell.bridge.launchReady; text: "Start game  ▶"; onClicked: rootShell.bridge.launchPrepared(); background: Rectangle { color: themeColors.green; radius: 9 } contentItem: Text { text: parent.text; color: "white"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } } }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: resourcesPage
        Item {
            ColumnLayout {
                anchors.fill: parent; anchors.topMargin: 8; spacing: 16
                Text { text: "Resources"; color: themeColors.ink; font.pixelSize: 26; font.bold: true }
                Surface {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    ColumnLayout { anchors.centerIn: parent; width: Math.min(parent.width - 50, 520); spacing: 12
                        Text { text: "✣"; color: themeColors.accent; font.pixelSize: 40; Layout.alignment: Qt.AlignHCenter }
                        Text { text: "Find your next favourite."; color: themeColors.ink; font.pixelSize: 20; font.bold: true; Layout.alignment: Qt.AlignHCenter }
                        Text { text: "The existing Widgets resource center is still the complete download experience. This QML experiment focuses on the instance-to-launch flow; Modrinth and CurseForge search are not wired into this shell yet."; color: themeColors.muted; font.pixelSize: 12; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                        Button { text: "Back to instances"; Layout.alignment: Qt.AlignHCenter; onClicked: go(1, "Instances") }
                    }
                }
            }
        }
    }
    Component {
        id: agentPage
        Item {
            ColumnLayout {
                anchors.fill: parent; anchors.topMargin: 8; spacing: 16
                RowLayout { Layout.fillWidth: true
                    ColumnLayout { spacing: 4; Text { text: "Agent workbench"; color: themeColors.ink; font.pixelSize: 26; font.bold: true } Text { text: "A player goal should stay simple. The careful work happens behind it."; color: themeColors.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true } }
                    Item { Layout.fillWidth: true }
                    Rectangle { radius: 10; color: rootShell.bridge.resolvedTheme === "light" ? "#fff3dc" : "#483a27"; implicitWidth: 100; implicitHeight: 28; Text { anchors.centerIn: parent; text: "EXPERIMENT"; color: themeColors.warn; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1 } }
                }
                Surface { Layout.fillWidth: true; Layout.preferredHeight: 190
                    ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 11
                        Text { text: "What would you like to do?"; color: themeColors.ink; font.pixelSize: 17; font.bold: true }
                        TextArea { Layout.fillWidth: true; Layout.fillHeight: true; placeholderText: "For example: Help me get this modpack ready to play with friends…"; wrapMode: TextEdit.Wrap; color: themeColors.ink; placeholderTextColor: themeColors.muted; background: Rectangle { radius: 11; color: themeColors.bg; border.color: themeColors.line } }
                        Text { text: "This goal box is a design prototype. It does not send a request to an AI model."; color: themeColors.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                Surface { Layout.fillWidth: true; Layout.fillHeight: true
                    Text { id: workflowHeading; anchors.left: parent.left; anchors.top: parent.top; anchors.leftMargin: 22; anchors.topMargin: 22; text: "A good task should show its work"; color: themeColors.ink; font.pixelSize: 16; font.bold: true }
                    RowLayout { id: workflowSteps; anchors.left: parent.left; anchors.right: parent.right; anchors.top: workflowHeading.bottom; anchors.leftMargin: 22; anchors.rightMargin: 22; anchors.topMargin: 22; height: 75; spacing: 12
                        Repeater { model: ["Understand", "Review", "Apply", "Verify", "Restore"]
                            delegate: Rectangle { required property string modelData; required property int index; Layout.fillWidth: true; Layout.preferredHeight: 75; radius: 12; color: themeColors.raised
                                Column { anchors.centerIn: parent; spacing: 7; Text { text: (index + 1).toString().padStart(2, "0"); color: themeColors.accent; font.pixelSize: 10; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter } Text { text: modelData; color: themeColors.ink; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter } }
                            }
                        }
                    }
                    Text { anchors.left: parent.left; anchors.right: parent.right; anchors.top: workflowSteps.bottom; anchors.leftMargin: 22; anchors.rightMargin: 22; anchors.topMargin: 22; text: "Current QML integration: instance discovery, cancellable launch preparation and explicit launch confirmation. AI tool execution, edit previews and restore actions remain in the existing Widgets application."; color: themeColors.muted; font.pixelSize: 11; wrapMode: Text.Wrap }
                }
            }
        }
    }
    Component {
        id: settingsPage
        Flickable {
            contentWidth: width; contentHeight: settingsColumn.implicitHeight; clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            ColumnLayout {
                id: settingsColumn; width: parent.width; spacing: 16
                ColumnLayout { Layout.topMargin: 8; spacing: 4; Text { text: "Settings"; color: themeColors.ink; font.pixelSize: 26; font.bold: true } Text { text: "A few essentials for this QML shell. Other settings stay in the full launcher."; color: themeColors.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true } }
                Surface { Layout.fillWidth: true; Layout.preferredHeight: 146
                    ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 11
                        Text { text: "APPEARANCE"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.2 }
                        Text { text: "Choose a theme"; color: themeColors.ink; font.pixelSize: 13; font.bold: true }
                        RowLayout { spacing: 8
                            Repeater { model: [{label:"System", key:"system"}, {label:"Dark", key:"dark"}, {label:"Light", key:"light"}]
                                delegate: Rectangle {
                                    required property var modelData
                                    implicitWidth: 88; implicitHeight: 34; radius: 9
                                    color: rootShell.bridge.theme === modelData.key ? themeColors.accent : themeColors.raised
                                    border.color: rootShell.bridge.theme === modelData.key ? themeColors.accent : themeColors.line
                                    Text { anchors.centerIn: parent; text: modelData.label; color: rootShell.bridge.theme === modelData.key ? "white" : themeColors.ink; font.pixelSize: 11; font.bold: rootShell.bridge.theme === modelData.key }
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: rootShell.bridge.setTheme(modelData.key) }
                                }
                            }
                        }
                    }
                }
                Surface { Layout.fillWidth: true; Layout.preferredHeight: 160
                    ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 10
                        Text { text: "GAME DIRECTORY"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.2 }
                        Text { text: "Existing instances are read from this folder. Changing it updates the saved launcher setting."; color: themeColors.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        RowLayout { Layout.fillWidth: true
                            TextField { id: gamePath; Layout.fillWidth: true; text: rootShell.bridge.gameDirectory; selectByMouse: true; color: themeColors.ink; background: Rectangle { radius: 10; color: themeColors.bg; border.color: themeColors.line } }
                            Button { text: "Apply"; onClicked: rootShell.bridge.setGameDirectory(gamePath.text); background: Rectangle { color: themeColors.accent; radius: 9 } contentItem: Text { text: parent.text; color: "white"; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
                        }
                    }
                }
                Surface { Layout.fillWidth: true; Layout.preferredHeight: 92; color: themeColors.raised
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 5
                        Text { text: "FULL EXPERIENCE"; color: themeColors.muted; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.1 }
                        Text { text: "The original Widgets interface remains the complete launcher. Start it with python main.py."; color: themeColors.ink; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }
    }
}

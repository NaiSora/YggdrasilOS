// Réglages personnels : appliqués directement (pas de droits administrateur).

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    title: "Réglages"

    Kirigami.FormLayout {
        QQC2.ComboBox {
            Kirigami.FormData.label: "Voix des outils :"
            textRole: "texte"
            valueRole: "valeur"
            model: [
                { texte: "Chaque outil parle à sa façon", valeur: "voix" },
                { texte: "Sobre : rien que les faits", valeur: "sobre" }
            ]
            currentIndex: indexOfValue(ygg.reglages.ton || "voix")
            onActivated: ygg.regler("ton", currentValue)
        }

        QQC2.ComboBox {
            Kirigami.FormData.label: "Thème :"
            textRole: "texte"
            valueRole: "valeur"
            model: [
                { texte: "Nuit (nuit, or et sauge)", valeur: "nuit" },
                { texte: "Aube (parchemin, or et sauge)", valeur: "aube" },
                { texte: "Selon l'heure (aube le jour, nuit le soir)", valeur: "auto" }
            ]
            currentIndex: indexOfValue(ygg.reglages.theme || "nuit")
            onActivated: ygg.regler("theme", currentValue)
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true }

        QQC2.Switch {
            Kirigami.FormData.label: "Ratatoskr :"
            text: "M'apporter les nouvelles (mises à jour, alertes)"
            checked: ygg.reglages.ratatoskr === true
            onToggled: ygg.regler("ratatoskr", checked)
        }
        QQC2.Switch {
            Kirigami.FormData.label: "Présage :"
            text: "Le présage de Mímir au premier terminal du jour"
            checked: ygg.reglages.presage !== false
            onToggled: ygg.regler("presage", checked)
        }
        QQC2.Switch {
            Kirigami.FormData.label: "Centre :"
            text: "Ouvrir Hliðskjálf à l'ouverture de session"
            checked: ygg.reglages.autostart !== false
            onToggled: ygg.regler("autostart", checked)
        }
    }
}

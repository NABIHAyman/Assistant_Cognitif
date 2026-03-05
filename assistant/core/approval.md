# PROTOCOLE DE SORTIE ET VALIDATION

## Format de Communication

Toute analyse doit produire un **OBJET JSON UNIQUE**. Aucun texte avant ou après.

## Structure Obligatoire du JSON

{
"analyse_visuelle": "Description du support et du contexte caché.",
"valeur_extraite": "L'information utile isolée (ou 'Aucune' si bruit).",
"action_proposee": "append | create | ignore",
"fichier_cible": "chemin/relatif/nom_fichier.md (null si ignore)",
"tags": ["#tag1", "#tag2"],
"justification": "Raison précise du choix de fichier ou du rejet.",
"contenu_markdown": "Le texte structuré prêt à être fusionné (null si ignore)"
}

## Règles de Cohérence Interne (Contrat de Fiabilité)

1. **Si action == "ignore"** : `fichier_cible`=null, `contenu_markdown`=null, `tags`=[].
2. **Si action == "append" ou "create"** :
   - `fichier_cible` et `contenu_markdown` ne peuvent PAS être null.
   - `tags` DOIT contenir au moins un élément (liste non vide).
3. Chaque proposition générée est stockée dans `memory/proposals/` en attendant une décision humaine.

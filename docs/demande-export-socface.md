# Demande d'export des données Socface

Message à envoyer **par toi** (préalable P de `PLAN.md`), au service FranceArchives et à
l'équipe Socface de l'INED. Je n'ai pas pu vérifier les adresses de contact depuis
l'environnement de développement : utilise le formulaire de contact du portail FranceArchives
et l'adresse indiquée sur le site du projet Socface (socface.site.ined.fr).

Remplace les passages entre crochets avant l'envoi.

---

**Objet** : Réutilisation des données Socface (recensements 1836-1936) : existe-t-il un export
en masse ?

Madame, Monsieur,

Généalogiste amateur, je consulte avec beaucoup d'intérêt la base de noms des recensements
issue du projet Socface sur FranceArchives. Je développe pour mon usage personnel un petit
moteur de recherche, installé sur mon seul ordinateur, qui croise ces recensements avec
d'autres sources publiques (fichier des décès de l'INSEE, Morts pour la France) et tolère les
erreurs de transcription.

Je souhaiterais savoir :

1. s'il existe, ou s'il est prévu, un **export en masse** des données de recensement
   (fichier CSV ou Parquet, archive par département, dump RDF ou point d'accès SPARQL) ;
2. sous quelle **licence** ces données peuvent être réutilisées (Licence Ouverte Etalab ou
   autre), et à quelles conditions ;
3. si l'export comprend, pour chaque personne : nom, prénoms, âge, sexe, lieu de naissance,
   profession, lien avec le chef de ménage, commune, année du recensement, cote, page et
   position de la ligne, lien vers l'image, et, s'il existe, le **score de confiance** de la
   transcription automatique ;
4. comment les corrections apportées aux transcriptions sont diffusées (nouvelles versions de
   l'export, fréquence).

L'usage serait strictement personnel : aucune republication des données, et la provenance de
chaque notice (service d'archives, cote, vue) serait toujours conservée et citée.

Si un tel export n'existe pas, une extraction limitée à quelques départements
([départements]) me serait déjà très utile.

Je vous remercie par avance de votre réponse et du travail considérable accompli par le
projet Socface.

Cordialement,

[Ton nom]

---

## Ce que la réponse permettra de faire

| Réponse | Suite dans le plan |
|---|---|
| Export en masse disponible | connecteur d'import au jalon 6, sans aucune requête vers le site |
| Dump RDF ou SPARQL contenant les recensements | connecteur RDF au jalon 6 |
| Rien de disponible | repli prévu au préalable P : connecteur à la demande, commune par commune, seulement si les conditions d'utilisation le permettent ; sinon lien de recherche pré-rempli vers FranceArchives |

# Projet d’agrégation et de veille personnalisée

Pour construire une application qui collecte chaque jour les actualités qui t’intéressent (cybersécurité, IA, automobile, horlogerie, musique, etc.), voici toutes les étapes à mener, avec les technologies associées et des références pour approfondir :

## 1. Collecter et normaliser les sources d’informations

- **Lister tes flux RSS ou URLs** dans un fichier de configuration (ex : `sources.json`) indiquant le nom de la source, sa catégorie, et l’URL du flux. Cela permet d’ajouter facilement de nouvelles sources sans recompiler le code.
- **Récupérer les flux RSS/Atom** en Python. Utilise la bibliothèque [feedparser](https://pypi.org/project/feedparser/). Par exemple : 
  ```python
  import feedparser
  feed_url = "https://exemple.com/rss"
  feed = feedparser.parse(feed_url)
  for entry in feed.entries:
      print(entry.title, entry.link, entry.published)
  ```
  Feedparser gère de nombreux formats de syndication (RSS, Atom) et extrait le titre, le lien, la date, la description, etc..  
- **Nettoyer et normaliser les données** : stocke les champs principaux de chaque article (titre, lien, date, source, etc.) dans une structure uniforme (par exemple un dictionnaire Python). Ainsi tous les articles issus de sources différentes auront les mêmes clés pour être traités ensuite.

## 2. Extraire le contenu complet des articles

- **Aller chercher le texte intégral** de chaque article via son URL. En effet, les RSS fournissent souvent seulement un résumé ou une intro. Pour récupérer le contenu complet, envoie une requête HTTP (avec `requests.get`) sur l’URL, puis extrait le texte principal de la page HTML.  
- **Utiliser Trafilatura** : cette bibliothèque est conçue pour extraire le contenu principal des pages web (titres, textes, métadonnées) en éliminant les éléments parasites (menus, pubs, etc.). Par exemple :  
  ```python
  import trafilatura
  html = trafilatura.fetch_url(article_url)
  text = trafilatura.extract(html)
  ```  
  Trafilatura prend en charge les pages web classiques et offre même la gestion de flux RSS/Atom. Elle est largement utilisée pour constituer des bases de textes nettoyés.  
- **Stocker les métadonnées** : conserve le titre, la date, la source, le lien, et éventuellement un résumé (inclus dans le RSS ou extrait) ainsi que le texte complet obtenu. Cela te permettra d’implémenter des fonctionnalités de recherche ou de filtrage plus tard.

## 3. Déduplication et regroupement des articles

- **Éliminer les doublons** : plusieurs sources peuvent relayer la même actualité. Pour ne pas afficher 5 fois le même sujet, on utilise la similarité sémantique. Une approche courante est de calculer un *embedding* (vecteur) pour chaque article (par ex. via un modèle de sentence-transformers ou l’API OpenAI) puis mesurer la similarité cosinus entre articles. Si la similarité > 0,95, on les considère comme dupliqués.  
- **Affiner la déduplication** : on peut confirmer le doublon avec un calcul de distance de Levenshtein sur les titres ou contenus, afin de réduire les faux positifs (p. ex. seuil 0,97 sur les titres).  
- **Grouper par sujet** : à partir des similarités, regroupe les articles d’un même événement. Par exemple, prends un article comme « parent » et associe-lui les autres sources liées. Lors de l’affichage, tu n’affiches qu’un seul résumé pour ce groupe, avec éventuellement la liste des sources associées. La méthode en trois étapes (embeddings, Levenshtein, choix de la source principale) est illustrée dans NewsCatcherAPI.  
- **Stockage dans une base de données** : pour gérer l’historique et empêcher la répétition des mêmes articles, on peut utiliser SQLite. Par exemple, crée une table `articles` avec les colonnes (id, titre, résumé, lien, source, date). À chaque collecte, tu n’insères que les nouveaux articles (et ignore ceux déjà en base), ce qui évite de retraiter les anciens.

## 4. Filtrage et classement par intérêt

- **Catégorisation thématique** : durant la collecte, associe chaque source à une catégorie fixe (cyber, IA, auto, horlogerie, musique, etc.). Tu peux aussi implémenter une fonction qui détecte la catégorie depuis le titre ou le contenu (mots-clés, ou même un petit modèle ML pour classifier le sujet).  
- **Scoring personnalisé** : attribue un score d’intérêt à chaque article selon tes préférences. Simplement, un article de la catégorie *Automobile* peut recevoir un bonus si l’automobile te passionne. Tu peux améliorer cela avec un modèle de langage : demander à ChatGPT (via l’API) de noter, sur une échelle 1–10, la pertinence d’un article pour un profil donné. Par exemple : « Est-ce que cet article sur la cybersécurité te semble important à lire si tu es étudiant en cybersécurité ? Pourquoi ? Note de 1 à 10. »  
- **Tri final** : garde ensuite par catégorie les articles avec le plus haut score ou ceux non lus. Tu peux également filtrer par date pour ne garder que les infos récentes (ex. 24h). En bref, tu construis un classement qui reflète tes sujets et ta priorité personnelle.

## 5. Génération de résumés et analyse IA

- **Résumé structuré avec un LLM** : pour chaque article ou groupe d’articles, fais résumer le contenu par un modèle de langage (ex. GPT-4 via l’API OpenAI). Structure la requête pour obtenir un format utile : par exemple, demande un « Résumé en 3-5 phrases » suivi d’une liste de « points clés ».  
- **Exemple de code OpenAI** : en Python, après `pip install openai`, utilise la librairie officielle pour appeler le modèle :
  ```python
  from openai import OpenAI
  client = OpenAI(api_key="TA_CLEF")
  response = client.chat.completions.create(
      model="gpt-4-turbo",
      messages=[
          {"role": "user", "content": 
           "Résume cet article en français, en listant les 2 points clés."}
      ]
  )
  résumé = response.choices[0].message.content
  ```
  Ce code (adapté de la documentation) montre comment appeler ChatGPT pour obtenir un texte généré.  
- **Sortie structurée** : dans le prompt, spécifie clairement la structure attendue (titre, résumé, « À retenir », etc.). Par exemple : « Donne-moi le titre de l’article, un résumé de 2-3 phrases, puis trois points importants sous forme de puces. » L’IA répondra dans ce format, ce qui facilitera l’affichage.  
- **Balises de contexte** : tu peux également utiliser l’historique (par ex. ce que tu as lu les jours précédents) pour que l’IA adapte son résumé à tes besoins (« Contexte : tu es un étudiant en cybersécurité. »). Cela reste optionnel mais peut rendre les résultats plus personnels.

## 6. Construction de l’interface utilisateur (avec Streamlit)

- **Pourquoi Streamlit ?** C’est une bibliothèque Python qui permet de créer en quelques lignes une application web interactive. Tu installes avec `pip install streamlit` puis écris ton script d’app. Pas besoin de frontend séparé.  
- **Affichage du briefing** : par exemple, crée une page principale qui affiche, par rubrique (Cyber, IA, Auto, etc.), les titres d’articles sélectionnés. Tu peux ajouter des widgets pour filtrer ou rechercher (`st.sidebar.selectbox` pour choisir une catégorie, `st.text_input` pour une recherche par mot-clé, etc.).  
- **Exemple de layout** : 
  - Une barre latérale avec tes catégories et options de tri.
  - Une zone principale où tu affiches un titre, le résumé IA et le lien cliquable pour chaque article. Utilise `st.write`, `st.markdown` ou `st.header` pour formater. Par exemple : 
    ```python
    import streamlit as st
    st.title("Mon Briefing du Jour")
    catégorie = st.sidebar.selectbox("Catégorie", ["Toutes", "Cyber", "IA", "Auto", "Horlogerie", "Musique"])
    articles = get_articles(cat=catégorie)  # ta fonction de fetch
    for art in articles:
        st.subheader(art["title"])
        st.write(art["summary"])
        st.markdown(f"[Voir la source]({art['url']})")
    ```
  - Avec Streamlit, dès que tu changes le code ou la sélection, l’affichage se met à jour automatiquement.  
- **Interactions avancées** : tu peux ajouter des boutons pour marquer un article comme « lu » ou « intéressant », et enregistrer ce retour en base pour affiner le score. Par exemple `st.button("👍 Intéressant")` à côté de chaque résumé.  
- **Déploiement** : Streamlit Community Cloud ou Heroku te permet de déployer l’appli accessible via navigateur. Sinon, tu peux la lancer localement chaque matin avec `streamlit run app.py`.

## 7. Automatisation quotidienne

- **Programmation** : le script de collecte + résumé peut être exécuté automatiquement chaque jour (ex. le matin). Sur Linux/macOS, utilise `cron` pour lancer un script Python quotidiennement. Sur Windows, le Planificateur de tâches fait de même.  
- **Étapes planifiées** : crontab peut simplement appeler `python collect_and_summarize.py`. Ce script importe tes sources, récupère les flux, met à jour la base, appelle l’IA pour les nouveaux articles, puis met à jour ce qu’affiche Streamlit.  
- **Envoi des notifications** (optionnel) : tu peux aussi envoyer un email ou un message Telegram/Slack avec le résumé du jour en plus de l’affichage Web. Par exemple, `python-telegram-bot` ou `smtplib` pour envoyer un mail automatisé avec le briefing.

## 8. Environnement et outils recommandés

- **Python 3 et venv** : installe la dernière version de Python 3. Crée un environnement virtuel (`python -m venv venv`) pour isoler les dépendances.  
- **IDE** : VS Code est un bon choix. Il supporte l’auto-complétion et tu peux ajouter des extensions Python et Git. Beaucoup d’IDEs intègrent maintenant des assistants IA (GitHub Copilot, etc.) pour t’aider lors du développement.  
- **Gestion de code** : stocke ton code sur GitHub pour la sécurité et l’historique (même si c’est privé).  
- **Bibliothèques clés** : 
  - `feedparser` (lire RSS),
  - `requests` (requêtes HTTP),
  - `trafilatura` (extraire texte complet),
  - `sqlite3` (base de données embarquée),
  - `openai` (API GPT pour résumé et analyse),
  - `sentence-transformers` ou `openai.embeddings` pour les embeddings,
  - `streamlit` (interface web).  
- **API Key OpenAI** : tu devras obtenir une clé API OpenAI pour résumer/analyser. Stocke-la en sécurité (par ex. dans un fichier `.env`).  
- **Vérification des données** : teste à chaque étape avec quelques articles pour t’assurer que l’extraction et les résumés sont corrects (surtout que l’IA peut parfois halluciner, donc vérifie qu’elle ne fait pas d’erreurs factuelles majeures).

## 9. Solutions aux problèmes potentiels

- **Flux changeant** : certains sites modifient leur RSS. Vérifie régulièrement tes sources. Trafilatura aide aussi via des sitemaps si disponible.  
- **Limites d’API** : l’API OpenAI est payante selon le volume de texte. Pour réduire la taille du texte envoyé, tu peux tronquer l’article ou le résumer en deux passes (chunking).  
- **Performance** : si tu gères beaucoup d’articles, pense à ne requêter l’IA que sur les articles les plus pertinents. Tu peux aussi paralléliser la collecte avec `asyncio` ou `concurrent.futures`.  
- **Données personnelles** : fais attention aux données sensibles (par ex. assure-toi que les sources sont fiables). Évite de publier ces informations en public si ton app utilise tes notes internes.

## 10. Implémentation IA actuelle

L'analyse IA est implémentée dans le bloc clairement identifié `BLOC IA` de `flux.py`.
Elle utilise Ollama et le modèle local gratuit `qwen2.5:3b` par défaut. Installe
Ollama depuis https://ollama.com, puis télécharge et démarre le modèle :

```powershell
ollama pull qwen2.5:3b
ollama serve
```

Dans un autre terminal, lance la collecte :

```powershell
python flux.py
```

Ce fonctionnement est gratuit à l'usage et les articles restent sur la machine. Les
paramètres principaux peuvent être modifiés dans `flux.py` (`DEFAULT_AI_MODEL`,
`DEFAULT_MAX_AI_ARTICLES`, `DEFAULT_OLLAMA_URL`, `AI_SYSTEM_PROMPT`) ou au lancement :

```powershell
python flux.py --ai-model qwen2.5:3b --max-ai-articles 100 --ollama-url http://localhost:11434/api/generate
```

`OLLAMA_MODEL` et `OLLAMA_URL` permettent de changer ces paramètres sans modifier le
code. `--without-ai` lance
une collecte locale sans appel réseau à l'IA. En l'absence de clé, ce mode de repli est
automatiquement utilisé et les articles restent classés avec leur score local.

Pour chaque article, l'IA reçoit le contenu, la catégorie, le score local et le contexte
correspondant de `preferences.json` (`profil`, `interets`, `exclure` et règles générales).
Elle écrit dans `articles.json` les champs `ai_summary`, `ai_key_points`,
`ai_recommendation`, `ai_relevance_score`, `ai_reason`, `ai_matched_interests` et
`final_score`. Le score final combine le score local à 45 % et l'évaluation IA à 55 %.

Les résultats sont mis en cache dans `ai_cache.json`. Le cache est réutilisé uniquement
si l'article, les préférences et le modèle sont identiques. Modifier `preferences.json`
ou le modèle force donc automatiquement une nouvelle analyse. Le fichier de cache peut
être supprimé manuellement pour tout recalculer.

## 11. Résumé du flux global

Pour synthétiser, voici comment ton système va fonctionner chaque jour :

1. **Collecte** : `python collect.py` lit `sources.json`, utilise `feedparser` pour récupérer les nouveaux liens d’articles.  
2. **Extraction** : pour chaque lien, `requests` + `trafilatura.extract` obtiennent le texte complet, mis dans la DB SQLite (avec déduplication).  
3. **Analyse IA** : sur les nouveaux articles, on appelle GPT-4 (via `openai.chat.completions`) pour générer un résumé structuré et éventuellement un score d’intérêt.  
4. **Classement** : on trie les articles par catégorie et score. On regroupe les duplicata pour ne garder qu’un « parent » par sujet (sources multiples).  
5. **Affichage** : enfin, `streamlit app.py` présente tout cela sous forme de briefing matinal : par section (Cyber, IA, Auto, Horlogerie, Musique), avec titres cliquables et résumés.  

Chaque étape utilise des outils bien connus : feedparser pour la collecte, Trafilatura pour l’extraction, OpenAI (ou transformers) pour la compréhension du texte, et Streamlit pour l’interface. Ce document récapitule l’ensemble des composants nécessaires au projet ; il te servira de référence pendant le développement. Bon courage dans la réalisation de ce système complet de veille personnelle !

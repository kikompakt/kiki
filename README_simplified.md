# Kiki Chat - Vereinfachtes KI-Kursstudio

Vereinfachtes System für automatisierte Kurserstellung mit OpenAI Assistenten.

## 🚀 Railway Deployment

### 1. Vorbereitung

1. **Repository erstellen**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git push origin main
   ```

2. **Railway Account**: Registrierung auf [Railway.app](https://railway.app)

### 2. Environment Variables (Railway)

Setzen Sie folgende Umgebungsvariablen in Railway:

```
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_secret_key_here
DATABASE_URL=(wird automatisch von Railway gesetzt)
PORT=(wird automatisch von Railway gesetzt)
```

### 3. Deployment

1. **Railway Projekt erstellen**:
   - Mit GitHub Repository verbinden
   - Railway erkennt automatisch die `railway.json`

2. **PostgreSQL hinzufügen**:
   - In Railway Dashboard: "Add Service" → "Database" → "PostgreSQL"
   - DATABASE_URL wird automatisch gesetzt

3. **Deploy**:
   - Railway startet automatisch den Deployment-Prozess
   - Start Command: `gunicorn --worker-class gevent --worker-connections 1000 --workers 1 --bind 0.0.0.0:$PORT app_simplified:app`

## 🔧 Lokale Entwicklung

```bash
# Virtual Environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oder
venv\Scripts\activate     # Windows

# Dependencies installieren
pip install -r requirements_simplified.txt

# Environment Variables (.env Datei)
OPENAI_API_KEY=your_key_here
SECRET_KEY=dev-secret-key
DATABASE_URL=sqlite:///kiki_chat.db

# Anwendung starten
python app_simplified.py
```

## 🤖 OpenAI Assistenten

Das System verwendet folgende vorkonfigurierte Assistenten:

- **Supervisor** (`asst_19FlW2QtTAIb7Z96f3ukfSre`) - Hauptsteuerung
- **Der Autor** (`asst_UCpHRYdDK2uPsb7no8Zw5Z0p`) - Content-Erstellung
- **Der Pädagoge** (`asst_tmj7Nz75MSwjPSrBf4KV2EIt`) - Didaktische Optimierung
- **Der Prüfer** (`asst_qH5a6MsVByLHP2ZLQ8gT8jg0`) - Qualitätsprüfung

Alle Assistenten verwenden das Modell `gpt-4.1-nano`.

## 📁 Vereinfachte Struktur

```
kiki-chat/
├── app_simplified.py          # Hauptanwendung
├── simple_orchestrator.py     # KI-Orchestrierung
├── knowledge_manager.py       # RAG-System (optional)
├── quality_assessment.py      # Qualitätsbewertung (optional)
├── templates/
│   └── chat_simple.html       # Chat-Interface
├── requirements_simplified.txt
├── railway.json
├── Procfile_simplified
└── start.py                   # Initialisierung
```

## 🔄 Workflow

1. **User-Input**: Benutzer beschreibt Kursidee
2. **Supervisor**: Erkennt Intent und startet 3-Schritt-Workflow
3. **Content Creator**: Erstellt Rohinhalt
4. **Didactic Expert**: Optimiert didaktisch
5. **Quality Checker**: Prüft und bewertet
6. **Output**: Fertiger Kurs wird angezeigt

## 📝 Standard-Benutzer

- **Admin**: `admin` / `admin123`
- **Demo**: `demo` / `demo123`

## 🐛 Troubleshooting

**Railway Logs ansehen**:
```bash
railway logs
```

**Häufige Probleme**:
- OpenAI API Key fehlt oder ungültig
- Assistant IDs nicht gefunden
- Datenbankverbindung fehlgeschlagen

## 📞 Support

Bei Problemen:
1. Railway Logs prüfen
2. Environment Variables kontrollieren
3. OpenAI Assistant Status überprüfen
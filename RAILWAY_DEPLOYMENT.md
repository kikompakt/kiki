# 🚀 Railway Deployment Guide

## Railway-Deployment für das Intelligente KI-Kursstudio

Dieses Guide führt Sie Schritt für Schritt durch das Deployment Ihrer Anwendung auf Railway.

---

## 📋 **Vorbereitung**

### 1. **Railway Account erstellen**
- Gehen Sie zu [railway.app](https://railway.app)
- Registrieren Sie sich mit GitHub
- Bestätigen Sie Ihre E-Mail-Adresse

### 2. **Railway CLI installieren (Optional)**
```bash
# macOS/Linux
curl -fsSL https://railway.app/install.sh | sh

# Windows
iwr https://railway.app/install.ps1 | iex
```

---

## 🚀 **Deployment-Optionen**

### **Option A: GitHub Integration (Empfohlen)**

#### **Schritt 1: Code auf GitHub hochladen**
```bash
# Falls noch nicht geschehen
git add .
git commit -m "Railway deployment ready"
git push origin main
```

#### **Schritt 2: Railway Projekt erstellen**
1. Gehen Sie zu [railway.app/dashboard](https://railway.app/dashboard)
2. Klicken Sie auf **"New Project"**
3. Wählen Sie **"Deploy from GitHub repo"**
4. Wählen Sie Ihr Repository: `intelligentes-ki-kursstudio`
5. Railway erkennt automatisch die Python-Anwendung

#### **Schritt 3: PostgreSQL-Datenbank hinzufügen**
1. Klicken Sie auf **"Add Service"** → **"Database"** → **"PostgreSQL"**
2. Railway erstellt automatisch eine PostgreSQL-Instanz
3. Die `DATABASE_URL` wird automatisch als Umgebungsvariable gesetzt

#### **Schritt 4: Umgebungsvariablen konfigurieren**
Gehen Sie zu **"Variables"** und fügen Sie hinzu:

```
OPENAI_API_KEY=your_openai_api_key_here
FLASK_SECRET_KEY=your_random_secret_key_here
```

#### **Schritt 5: Deployment starten**
- Railway startet automatisch das Deployment
- Die Anwendung verwendet `app_railway.py` (siehe Procfile)
- PostgreSQL wird automatisch initialisiert

---

### **Option B: Railway CLI**

#### **Schritt 1: Railway CLI einrichten**
```bash
# Anmelden
railway login

# Projekt erstellen
railway init
```

#### **Schritt 2: PostgreSQL hinzufügen**
```bash
railway add postgresql
```

#### **Schritt 3: Umgebungsvariablen setzen**
```bash
railway variables set OPENAI_API_KEY="your_openai_api_key_here"
railway variables set FLASK_SECRET_KEY="your_random_secret_key_here"
```

#### **Schritt 4: Deployen**
```bash
railway up
```

---

## 🔧 **Wichtige Railway-Konfiguration**

### **Automatisch erkannte Dateien:**
- **`Procfile`**: `web: gunicorn app_railway:app`
- **`requirements.txt`**: Alle Python-Dependencies
- **`runtime.txt`**: `python-3.10.12`

### **Automatisch gesetzte Umgebungsvariablen:**
- **`DATABASE_URL`**: PostgreSQL-Verbindungsstring
- **`PORT`**: Port für den Webserver (automatisch)

### **Von Ihnen zu setzende Variablen:**
- **`OPENAI_API_KEY`**: Ihr OpenAI API-Schlüssel (**ERFORDERLICH**)
- **`FLASK_SECRET_KEY`**: Sicherheitsschlüssel für Sessions (**ERFORDERLICH**)

---

## 🎯 **Nach dem Deployment**

### **1. Erste Anmeldung**
- **Admin-Login:** `admin` / `admin123`
- **User-Login:** `user` / `user123`

### **2. URLs**
- **Hauptanwendung:** `https://ihre-app.railway.app`
- **Admin-Panel:** `https://ihre-app.railway.app/admin`
- **Chat-Interface:** `https://ihre-app.railway.app/chat`

### **3. Datenbank-Initialisierung**
Die Datenbank wird beim ersten Start automatisch initialisiert:
- Standard-User werden erstellt
- Default-Assistants werden konfiguriert
- Standard-Workflows werden geladen

---

## 📊 **Monitoring & Logs**

### **Railway Dashboard:**
- **Deployments**: Status aller Deployments
- **Metrics**: CPU, Memory, Network Usage
- **Logs**: Real-time Application Logs
- **Variables**: Umgebungsvariablen-Management

### **Log-Befehle (CLI):**
```bash
# Live-Logs anzeigen
railway logs

# Service-spezifische Logs
railway logs --service web
```

---

## 🔒 **Sicherheit & Produktions-Setup**

### **Kritische Sicherheitseinstellungen:**
1. **Starke Passwörter:** Ändern Sie die Default-Passwörter nach dem ersten Login
2. **Secret Key:** Verwenden Sie einen starken, zufälligen `FLASK_SECRET_KEY`
3. **API-Keys:** Verwahren Sie Ihren OpenAI API-Key sicher

### **Empfohlene Einstellungen:**
```bash
# Starker Secret Key generieren (Python)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Umgebungsvariable setzen
railway variables set FLASK_SECRET_KEY="generierter_key_hier"
```

---

## 🛠️ **Troubleshooting**

### **Häufige Probleme:**

#### **1. Build Fehler**
```bash
# Dependencies prüfen
railway logs | grep "requirements.txt"

# Lokale Tests
pip install -r requirements.txt
python app_railway.py
```

#### **2. Datenbank-Verbindung**
```bash
# DATABASE_URL prüfen
railway variables

# Datenbank-Status prüfen
railway status
```

#### **3. OpenAI API Fehler**
```bash
# API-Key prüfen
railway variables get OPENAI_API_KEY

# Logs nach API-Fehlern durchsuchen
railway logs | grep "OpenAI"
```

### **Support-Kanäle:**
- **Railway Docs:** [docs.railway.app](https://docs.railway.app)
- **Railway Discord:** Community-Support
- **GitHub Issues:** Projekt-spezifische Probleme

---

## 🎉 **Erfolgreiche Deployment-Checkliste**

- [ ] ✅ GitHub Repository ist aktuell
- [ ] ✅ Railway-Projekt erstellt
- [ ] ✅ PostgreSQL-Datenbank hinzugefügt
- [ ] ✅ `OPENAI_API_KEY` gesetzt
- [ ] ✅ `FLASK_SECRET_KEY` gesetzt
- [ ] ✅ Deployment erfolgreich
- [ ] ✅ Anwendung erreichbar
- [ ] ✅ Admin-Login funktioniert
- [ ] ✅ Chat-Interface funktioniert
- [ ] ✅ Assistants sind konfiguriert

---

## 📈 **Next Steps**

Nach erfolgreichem Deployment können Sie:
1. **Custom Domain** in Railway konfigurieren
2. **SSL-Zertifikat** automatisch aktivieren
3. **Monitoring & Alerts** einrichten
4. **Backup-Strategien** für die Datenbank implementieren

**🚀 Ihr Intelligentes KI-Kursstudio ist jetzt live auf Railway!** 
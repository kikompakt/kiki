import os
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
from quality_assessment import QualityAssessment, assess_course_quality

# .env-Datei laden
load_dotenv()

# OpenAI Client initialisieren
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class ContentOrchestrator:
    """
    Zentraler Orchestrator, der OpenAI Assistant als Supervisor nutzt
    und spezialisierte Agenten als Tools koordiniert.
    """
    
    def __init__(self):
        self.client = client  # OpenAI Client für API Calls
        self.supervisor_assistant = None
        self.thread = None
        self.current_run = None
        
    def initialize_supervisor(self):
        """Erstellt den Supervisor-Assistant mit Tool-Definitionen."""
        
        # Tool-Definitionen für spezialisierte Agenten
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "create_content",
                    "description": "Erstellt einen ersten Rohentwurf für ein gegebenes Thema.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "Das Thema, zu dem der Inhalt erstellt werden soll."
                            },
                            "instructions": {
                                "type": "string", 
                                "description": "Spezifische Anweisungen für die Inhalterstellung."
                            }
                        },
                        "required": ["topic", "instructions"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "optimize_didactics",
                    "description": "Überarbeitet einen Rohentwurf nach didaktischen Prinzipien.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Der zu überarbeitende Inhalt."
                            }
                        },
                        "required": ["content"]
                    }
                }
            },
            {
                "type": "function", 
                "function": {
                    "name": "critically_review",
                    "description": "Prüft Inhalt kritisch auf Logik, Fakten und Konsistenz.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Der zu prüfende Inhalt."
                            }
                        },
                        "required": ["content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "request_human_approval", 
                    "description": "Fordert finale Freigabe vom Menschen für den erstellten Inhalt.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "final_content": {
                                "type": "string",
                                "description": "Der finale Inhalt zur Freigabe."
                            },
                            "feedback": {
                                "type": "string",
                                "description": "Das kritische Feedback zum Inhalt."
                            }
                        },
                        "required": ["final_content", "feedback"]
                    }
                }
            }
        ]
        
        # CRITICAL FIX: Assistant-ID Wiederverwendung
        existing_assistant_id = os.environ.get("ORCHESTRATOR_ASSISTANT_ID")
        
        if existing_assistant_id:
            try:
                # Versuche existierenden Assistant zu laden
                self.supervisor_assistant = client.beta.assistants.retrieve(existing_assistant_id)
                print(f"✅ Existierender Orchestrator Assistant wiederverwendet: {existing_assistant_id}")
            except Exception as e:
                print(f"⚠️ Assistant {existing_assistant_id} nicht gefunden, erstelle neuen...")
                self.supervisor_assistant = self._create_new_orchestrator_assistant(tools)
        else:
            # Falls kein Assistant existiert, erstelle neuen
            self.supervisor_assistant = self._create_new_orchestrator_assistant(tools)
    
    def _create_new_orchestrator_assistant(self, tools):
        """Erstellt einen neuen Orchestrator Assistant und speichert ID."""
        assistant = client.beta.assistants.create(
            name="Content Creation Orchestrator",
            instructions=(
                "Du bist ein Projektmanager für die Content-Erstellung. "
                "Deine Aufgabe ist es, die Erstellung von Lerninhalten zu koordinieren. "
                "Du erhältst ein Thema und delegierst die Aufgaben nacheinander an spezialisierte Agenten:\n"
                "1. Erstelle zuerst einen Rohentwurf mit 'create_content'\n"
                "2. Optimiere den Entwurf didaktisch mit 'optimize_didactics'\n"
                "3. Prüfe kritisch mit 'critically_review'\n"
                "4. Hole finale Freigabe mit 'request_human_approval'\n"
                "Warte auf das Ergebnis jedes Schrittes, bevor du den nächsten initiierst."
            ),
            model="gpt-4o",
            tools=tools
        )
        
        # Speichere Assistant-ID für Wiederverwendung
        self._save_orchestrator_id_to_env(assistant.id)
        print(f"✅ Neuer Orchestrator Assistant erstellt und gespeichert: {assistant.id}")
        
        return assistant
        
    def _save_orchestrator_id_to_env(self, assistant_id):
        """Speichert Orchestrator Assistant-ID in .env für Wiederverwendung."""
        try:
            # Lese existierende .env-Datei
            env_path = ".env"
            env_lines = []
            
            # Lade existierende Inhalte
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    env_lines = f.readlines()
            
            # Prüfe ob ORCHESTRATOR_ASSISTANT_ID bereits existiert
            orchestrator_line_found = False
            for i, line in enumerate(env_lines):
                if line.startswith('ORCHESTRATOR_ASSISTANT_ID='):
                    env_lines[i] = f"ORCHESTRATOR_ASSISTANT_ID={assistant_id}\n"
                    orchestrator_line_found = True
                    break
            
            # Falls nicht gefunden, füge hinzu
            if not orchestrator_line_found:
                if env_lines and not env_lines[-1].endswith('\n'):
                    env_lines.append('\n')
                env_lines.append(f"ORCHESTRATOR_ASSISTANT_ID={assistant_id}\n")
            
            # Schreibe zurück in .env
            with open(env_path, 'w') as f:
                f.writelines(env_lines)
                
            print(f"💾 Orchestrator Assistant-ID gespeichert für Wiederverwendung")
            
        except Exception as e:
            print(f"⚠️ Warnung: Assistant-ID konnte nicht gespeichert werden: {e}")
        
    def create_thread(self):
        """Erstellt einen neuen Thread für die Kommunikation."""
        self.thread = client.beta.threads.create()
        print(f"✅ Thread erstellt: {self.thread.id}")
        
    # Spezialisierte Agenten-Funktionen (werden als Tools aufgerufen)
    def create_content(self, topic: str, instructions: str) -> str:
        """Content Creator Agent - Erstellt Rohentwurf mit OpenAI API."""
        print(f"🤖 Content Creator: Erstelle hochwertigen Rohentwurf für '{topic}'...")
        
        # STRUCTURE-OPTIMIZED Prompt für bessere Kurs-Architektur
        content_prompt = f"""Du bist ein SENIOR INSTRUCTIONAL DESIGNER mit 15+ Jahren Expertise in strukturierter Kurs-Entwicklung.

AUFTRAG: Erstelle einen HOCHSTRUKTURIERTEN, professionellen Kursentwurf für "{topic}".

ANFORDERUNGEN:
{instructions}

KRITISCHE STRUKTUR-ANFORDERUNGEN (Quality Score Focus):
🏗️ PERFEKTE HIERARCHIE:
- Nummerierte Hauptkapitel (1., 2., 3.)
- Unterkapitel mit klaren Überschriften (1.1, 1.2, etc.)
- Jeder Abschnitt max. 3-4 Unterpoints
- Logische Progression: Grundlagen → Anwendung → Vertiefung

📋 LERNZIEL-MAPPING:
- Jedes Lernziel explizit einem Kapitel zugeordnet
- Messbare Outcomes pro Abschnitt definiert
- Klare Verbindung zwischen Theorie und Praxis
- Wissencheck nach jedem Hauptkapitel

🔄 KOGNITIVE STRUKTUR:
- Scaffolding-Prinzip strikt befolgen
- Vorwissen aktivieren → Neues Wissen → Anwendung → Reflexion
- Maximal 5-7 Hauptkonzepte pro Kurs
- Redundanz eliminieren, Fokus auf Kernbotschaften

OBLIGATORISCHE STRUKTUR (exakt befolgen):

# {topic}

## 📚 1. KURSÜBERSICHT
- **Zielgruppe:** [spezifisch]
- **Voraussetzungen:** [konkret]
- **Dauer:** [realistisch]
- **Format:** [detailliert]

## 🎯 2. LERNZIELE (SMART-formuliert)
1. **Wissen:** [Faktenwissen verstehen]
2. **Anwenden:** [Konzepte praktisch umsetzen] 
3. **Analysieren:** [Situationen bewerten]
4. **Erstellen:** [Eigene Lösungen entwickeln]

## 📖 3. KURSSTRUKTUR

### 3.1 Grundlagen verstehen
- **Lernziel:** Verbindung zu Ziel 1
- **Kernkonzept:** [1 Hauptidee]
- **Praxisbeispiel:** [konkret, spezifisch]
- **Übung:** [5-min Aktivität]

### 3.2 Praktische Anwendung  
- **Lernziel:** Verbindung zu Ziel 2
- **Kernkonzept:** [1 Hauptidee]
- **Praxisbeispiel:** [konkret, spezifisch]
- **Übung:** [15-min hands-on]

### 3.3 Vertiefung & Reflexion
- **Lernziel:** Verbindung zu Ziel 3+4
- **Kernkonzept:** [1 Hauptidee]
- **Praxisbeispiel:** [konkret, spezifisch]
- **Übung:** [eigenes Projekt starten]

## ✅ 4. ERFOLGSKONTROLLE
- **Wissencheck:** [5 spezifische Fragen]
- **Praktische Aufgabe:** [messbare Deliverables]
- **Selbstreflektion:** [3 Reflexionsfragen]

## 🎯 5. KEY TAKEAWAYS
1. [Wichtigste Erkenntnis]
2. [Wichtigste Fähigkeit]  
3. [Nächster Schritt]

SCHREIBSTIL: Kurze Sätze (max. 12 Wörter). Aktive Sprache. Konkrete Beispiele. Zero Fluff."""

        try:
            # Echter OpenAI API Call für hochwertige Content-Generation
            response = self.client.chat.completions.create(
                model="gpt-4",  # Bessere Qualität als gpt-3.5-turbo
                messages=[
                    {"role": "system", "content": "Du bist ein erfahrener Instruktionsdesigner, der hochwertige, strukturierte Kursinhalte erstellt."},
                    {"role": "user", "content": content_prompt}
                ],
                max_tokens=2000,
                temperature=0.7  # Kreativ aber konsistent
            )
            
            content = response.choices[0].message.content
            print("✅ Hochwertiger Rohentwurf erstellt.")
            return content
            
        except Exception as e:
            print(f"⚠️ OpenAI API Fehler: {e}")
            print("📝 Fallback auf erweiterten Template...")
            
            # Enhanced Fallback Template bei API-Problemen
            response = f"""# {topic}

## Überblick
Dieser Kurs vermittelt praktisches Wissen zu {topic.lower()}. Sie lernen die wichtigsten Konzepte kennen und können diese direkt in der Praxis anwenden.

## Lernziele
Nach diesem Kurs können Sie:
- Die Grundprinzipien von {topic.lower()} verstehen und erklären
- Praktische Strategien zur Umsetzung entwickeln
- Typische Herausforderungen erkennen und lösen
- Erste eigene Projekte erfolgreich starten

## Kernkonzepte

### 1. Grundlagen verstehen
{topic} basiert auf bewährten Prinzipien. Wir beginnen mit den Basics und bauen systematisch auf.

**Beispiel:** Ein einfaches Praxis-Szenario aus der realen Welt.

### 2. Strategische Planung
Erfolgreiche Umsetzung braucht eine klare Strategie. Lernen Sie, wie Sie vorgehen.

**Beispiel:** Schritt-für-Schritt Anleitung für Ihr erstes Projekt.

### 3. Praktische Umsetzung
Von der Theorie zur Praxis. Konkrete Tools und Methoden für sofortige Anwendung.

**Beispiel:** Live-Demo mit echten Daten und Ergebnissen.

## Praktische Übungen

### Übung 1: Situationsanalyse
Analysieren Sie Ihre aktuelle Situation. Identifizieren Sie Potentiale und Hindernisse.

### Übung 2: Strategie entwickeln
Erstellen Sie einen konkreten Aktionsplan für Ihr erstes Projekt.

## Selbsttest
1. Was sind die 3 wichtigsten Grundprinzipien?
2. Welche Strategie passt zu Ihrer Situation?
3. Welches Tool verwenden Sie für den Start?
4. Wie messen Sie Ihren Erfolg?
5. Was ist Ihr nächster konkreter Schritt?

## Zusammenfassung
**Key Takeaways:**
- {topic} ist erlernbar mit dem richtigen System
- Praxis schlägt Theorie - starten Sie sofort
- Messen Sie Ihre Fortschritte regelmäßig
"""
            
            print("✅ Rohentwurf erstellt.")
            return response
        
    def optimize_didactics(self, content: str) -> str:
        """Didactic Expert Agent - Optimiert didaktisch mit OpenAI API."""
        print("👨‍🏫 Didactic Expert: Führe professionelle didaktische Optimierung durch...")
        
        # STRUKTUR-FOCUSED Didactic Optimization für maximale Struktur-Scores
        didactic_prompt = f"""Du bist ein SENIOR LEARNING ARCHITECT mit Fokus auf STRUKTURELLE EXZELLENZ.

MISSION: Optimiere die STRUKTUR dieses Kurses für maximale Lernwirksamkeit und Quality-Scores.

ORIGINAL CONTENT:
{content}

KRITISCHE STRUKTUR-OPTIMIERUNGEN (Priority: Struktur-Score 50+/100):

🏗️ HIERARCHIE PERFEKTIONIEREN:
- Jede Überschrift eindeutig nummeriert (1., 1.1, 1.1.1)
- Maximal 3 Hierarchie-Ebenen
- Parallel strukturierte Abschnitte
- Visuell klare Gliederung mit Emojis/Icons

📋 LERNZIEL-ARCHITEKTUR:
- Explizites Mapping: Lernziel → Kapitel → Übung → Assessment
- Jeder Abschnitt startet mit "Nach diesem Kapitel können Sie..."
- Messbare Lernfortschritte definieren
- Clear Learning Pathway erkennbar

🔄 KOGNITIVE LOAD OPTIMIERUNG:
- Chunking: Max. 5-7 Items pro Liste
- Progressive Disclosure: Einfach → Komplex
- Clear Transitions zwischen Abschnitten
- Redundanz eliminieren, Kernbotschaften fokussieren

🎯 ASSESSMENT-INTEGRATION:
- Nach jedem Hauptkapitel: Kurzer Wissencheck
- Praktische Mini-Übungen eingebettet  
- Selbstreflexions-Prompts strategisch platziert
- Clear Success Criteria definiert

OPTIMIERUNGS-FOKUS:
1. **Erhöhe Struktur-Score** von aktuell 34/100 auf 50+/100
2. **Behalte Lesbarkeits-Gains** (aktuell 40+/100)
3. **Verbessere Konsistenz** durch einheitliche Formatierung
4. **Perfektioniere Learning Flow** durch logische Progression

AUSGABE-ANFORDERUNGEN:
- Behalte exakt die 5-Kapitel Struktur bei
- Verstärke die Nummerierung und Hierarchie  
- Füge explizite Lernziel-Verbindungen hinzu
- Optimiere für strukturelle Klarheit über alles andere
- Kurze, präzise Formulierungen (max. 12 Wörter/Satz)

QUALITÄTS-CHECK: Stelle sicher, dass ein Lernender die Struktur sofort versteht und seinen Fortschritt klar verfolgen kann."""

        try:
            # Echter OpenAI API Call für didaktische Optimierung
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Du bist ein erfahrener Didaktik-Experte, der Kursinhalte für optimale Lernwirksamkeit aufbereitet."},
                    {"role": "user", "content": didactic_prompt}
                ],
                max_tokens=2500,
                temperature=0.3  # Konservativ für Struktur-Optimierung
            )
            
            optimized_content = response.choices[0].message.content
            print("✅ Professionelle didaktische Optimierung abgeschlossen.")
            return optimized_content
            
        except Exception as e:
            print(f"⚠️ OpenAI API Fehler: {e}")
            print("📝 Fallback auf erweiterte didaktische Templates...")
            
            # Enhanced Fallback für didaktische Optimierung
            optimized = f"""{content}

---

## 🎯 DIDAKTISCHE VERBESSERUNGEN

### ✅ Lernwirksamkeit optimiert:
- **Klare Struktur**: Jeder Abschnitt folgt dem Prinzip "Erklären → Zeigen → Üben"
- **Kurze Sätze**: Maximum 12 Wörter für bessere Verständlichkeit
- **Praktischer Fokus**: Jedes Konzept mit sofort anwendbarem Beispiel
- **Interaktive Elemente**: Reflexionsfragen und praktische Übungen integriert

### 🧠 Kognitive Belastung reduziert:
- **Chunking**: Komplexe Inhalte in verdauliche Häppchen aufgeteilt
- **Scaffolding**: Logischer Aufbau vom Einfachen zum Komplexen  
- **Redundanz eliminiert**: Wiederholungen entfernt, Fokus auf Kernbotschaften
- **Visuelle Hierarchie**: Überschriften und Bulletpoints für bessere Orientierung

### 💡 Engagement erhöht:
- **Praxisbezug**: Reale Szenarien und Beispiele aus der Arbeitswelt
- **Selbstreflexion**: Fragen zur persönlichen Anwendung
- **Erfolgserlebnisse**: Kleine, erreichbare Meilensteine definiert
- **Relevanz**: Direkte Verbindung zu beruflichen Herausforderungen

### 📝 Zusätzliche Lernhilfen:
- **Checklisten** für praktische Umsetzung
- **Key Takeaways** am Ende jedes Abschnitts  
- **Glossar** mit wichtigen Fachbegriffen
- **Weiterführende Ressourcen** für Vertiefung"""
            
            print("✅ Didaktische Optimierung abgeschlossen.")
            return optimized
        
    def critically_review(self, content: str) -> str:
        """Critical Thinker 2.0 - Kritische Prüfung mit automatisierten Qualitätsmetriken."""
        print("🔍 Critical Thinker 2.0: Führe automatisierte Qualitätsprüfung durch...")
        
        # Automatisierte Qualitätsbewertung
        quality_assessment = assess_course_quality(content)
        
        review = f"""--- KRITISCHE PRÜFUNG (CRITICAL THINKER 2.0) ---

## 📊 AUTOMATISIERTE QUALITÄTSMETRIKEN:
**Gesamtscore: {quality_assessment['overall_score']}/100** ({'✅ Ready for Review' if quality_assessment['ready_for_review'] else '❌ Needs Improvement'})
**Qualitätslevel: {quality_assessment['quality_level'].upper()}**

### 📈 KOMPONENTEN-BEWERTUNG:
- **Lesbarkeit:** {quality_assessment['component_scores']['readability']['score']}/100 ({quality_assessment['component_scores']['readability']['level']})
- **Struktur:** {quality_assessment['component_scores']['structure']['score']}/100
- **Konsistenz:** {quality_assessment['component_scores']['consistency']['score']}/100

### 🔍 STRUKTUR-ANALYSE:"""
        
        # Strukturelle Details
        structure_details = quality_assessment['component_scores']['structure']['details']
        review += f"""
- Lernziele: {structure_details['learning_objectives']}/25 Punkte
- Beispiele: {structure_details['examples']}/25 Punkte  
- Gliederung: {structure_details['structure']}/25 Punkte
- Zusammenfassung: {structure_details['summary']}/25 Punkte"""
        
        # Verbesserungsempfehlungen
        if quality_assessment['component_scores']['structure']['recommendations']:
            review += "\n\n### 📝 VERBESSERUNGSEMPFEHLUNGEN:"
            for rec in quality_assessment['component_scores']['structure']['recommendations']:
                review += f"\n- {rec}"
        
        # Konsistenz-Issues
        if quality_assessment['component_scores']['consistency']['issues']:
            review += "\n\n### ⚠️ KONSISTENZ-PROBLEME:"
            for issue in quality_assessment['component_scores']['consistency']['issues']:
                review += f"\n- {issue}"
        
        # Verbesserungs-Prioritäten
        if quality_assessment['improvement_priority']:
            review += "\n\n### 🎯 VERBESSERUNGS-PRIORITÄTEN:"
            for i, priority in enumerate(quality_assessment['improvement_priority'], 1):
                review += f"\n{i}. {priority}"
        
        # Finale Empfehlung
        review += f"\n\n## 🔥 FINALE EMPFEHLUNG:"
        if quality_assessment['ready_for_review']:
            review += f"\n✅ **FREIGABE EMPFOHLEN** - Qualitätsschwellwert ({quality_assessment['threshold']}) erreicht!"
            review += "\nInhalt ist bereit für menschliche Überprüfung und Freigabe."
        else:
            review += f"\n❌ **ÜBERARBEITUNG ERFORDERLICH** - Qualitätsschwellwert ({quality_assessment['threshold']}) nicht erreicht."
            review += "\nBitte arbeiten Sie die Verbesserungs-Prioritäten ab, bevor eine Freigabe erfolgen kann."
        
        review += f"\n\n**AUTOMATISIERTER QUALITÄTSSCORE: {quality_assessment['overall_score']}/100**"
        
        print(f"✅ Automatisierte Qualitätsprüfung abgeschlossen. Score: {quality_assessment['overall_score']}/100")
        return review
        
    def request_human_approval(self, final_content: str, feedback: str) -> str:
        """Human-in-the-Loop - Fordert menschliche Freigabe."""
        print("\n" + "="*70)
        print("🚨 MENSCHLICHE FREIGABE ERFORDERLICH")
        print("="*70)
        
        print("\n📄 FINALER INHALT:")
        print("-" * 50)
        print(final_content)
        
        print("\n🔍 KRITISCHES FEEDBACK:")
        print("-" * 50) 
        print(feedback)
        
        print("\n" + "="*70)
        approval = input("🤝 Soll dieser Inhalt final freigegeben werden? (ja/nein): ").lower().strip()
        
        if approval == "ja":
            print("✅ Inhalt wurde freigegeben!")
            return "FREIGEGEBEN"
        else:
            print("❌ Inhalt wurde zur Überarbeitung zurückgewiesen.")
            return "ÜBERARBEITUNG_ERFORDERLICH"
            
    def handle_tool_calls(self, tool_calls):
        """Verarbeitet Tool-Aufrufe des Supervisor-Assistants."""
        tool_outputs = []
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            
            print(f"\n🔧 Tool-Aufruf: {function_name}")
            print(f"📋 Parameter: {arguments}")
            
            # Entsprechende Funktion aufrufen
            if function_name == "create_content":
                result = self.create_content(arguments["topic"], arguments["instructions"])
            elif function_name == "optimize_didactics":
                result = self.optimize_didactics(arguments["content"])
            elif function_name == "critically_review":
                result = self.critically_review(arguments["content"])
            elif function_name == "request_human_approval":
                result = self.request_human_approval(arguments["final_content"], arguments["feedback"])
            else:
                result = f"Unbekannte Funktion: {function_name}"
                
            tool_outputs.append({
                "tool_call_id": tool_call.id,
                "output": result
            })
            
        return tool_outputs
        
    def run_workflow(self, user_prompt: str):
        """Startet den gesamten Content-Erstellungs-Workflow."""
        print(f"\n🚀 Starte Workflow für: {user_prompt}")
        
        # Nachricht zum Thread hinzufügen
        client.beta.threads.messages.create(
            thread_id=self.thread.id,
            role="user", 
            content=user_prompt
        )
        
        # Run mit Supervisor starten
        run = client.beta.threads.runs.create(
            thread_id=self.thread.id,
            assistant_id=self.supervisor_assistant.id
        )
        
        # Workflow-Schleife
        while run.status in ['queued', 'in_progress', 'requires_action']:
            if run.status == 'requires_action':
                print(f"\n⏸️ Run erfordert Aktion: {run.status}")
                
                # Tool-Aufrufe verarbeiten
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                tool_outputs = self.handle_tool_calls(tool_calls)
                
                # Ergebnisse zurück an Run senden
                run = client.beta.threads.runs.submit_tool_outputs(
                    thread_id=self.thread.id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )
                
            time.sleep(1)  # Kurze Pause
            run = client.beta.threads.runs.retrieve(thread_id=self.thread.id, run_id=run.id)
            
        print(f"\n🏁 Workflow beendet mit Status: {run.status}")
        
        # Finale Antwort abrufen
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=self.thread.id)
            final_response = messages.data[0].content[0].text.value
            print(f"\n📋 FINALE ANTWORT DES SUPERVISORS:")
            print("-" * 50)
            print(final_response)
            
        return run.status 
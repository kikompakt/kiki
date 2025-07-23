#!/usr/bin/env python3
"""
Test Use Cases für Multi-Agenten-Kursgenerator
MVP-TODO-003: Konkrete Szenarien für System-Validierung
"""

import sys
import json
from datetime import datetime
from orchestrator import ContentOrchestrator
from quality_assessment import QualityAssessment

class TestUseCases:
    def __init__(self):
        self.orchestrator = ContentOrchestrator()
        self.quality_assessment = QualityAssessment()
        self.results = []
    
    def test_case_1_marketing_beginner(self):
        """
        Test Case 1: Marketing-Kurs für Anfänger
        Zielgruppe: Unternehmer ohne Marketing-Vorkenntnisse
        Lernziel: Grundlagen digitales Marketing in 4 Wochen
        """
        print("🎯 TEST CASE 1: Marketing-Kurs für Anfänger")
        print("="*60)
        
        course_request = {
            "title": "Digitales Marketing für Einsteiger",
            "target_audience": "Unternehmer und Selbstständige ohne Marketing-Vorkenntnisse",
            "learning_objectives": [
                "Verstehen der wichtigsten Digital Marketing Kanäle",
                "Erstellen einer einfachen Marketing-Strategie", 
                "Grundlagen Social Media Marketing",
                "Messbare Ziele definieren und ROI berechnen"
            ],
            "duration": "4 Wochen",
            "format": "Online-Kurs mit praktischen Übungen",
            "complexity_level": "Beginner"
        }
        
        print(f"📋 Kurs-Anfrage: {course_request['title']}")
        print(f"🎓 Zielgruppe: {course_request['target_audience']}")
        print(f"⏱️ Dauer: {course_request['duration']}")
        
        # Test durchführen
        result = self._run_test_workflow(course_request, "marketing_beginner")
        return result
    
    def test_case_2_data_analysis_advanced(self):
        """
        Test Case 2: Datenanalyse-Kurs für Fortgeschrittene
        Zielgruppe: Data Analysts mit Python-Grundkenntnissen
        Lernziel: Advanced Analytics & Machine Learning
        """
        print("\n🎯 TEST CASE 2: Datenanalyse-Kurs für Fortgeschrittene")
        print("="*60)
        
        course_request = {
            "title": "Advanced Data Analytics mit Python",
            "target_audience": "Data Analysts mit 1-2 Jahren Python-Erfahrung",
            "learning_objectives": [
                "Statistische Modellierung und Hypothesentests",
                "Machine Learning Algorithmen implementieren",
                "Datenvisualisierung mit Plotly und Seaborn",
                "A/B Testing und experimentelles Design",
                "Big Data Processing mit Pandas und Dask"
            ],
            "duration": "8 Wochen",
            "format": "Hands-on Workshop mit realen Datasets",
            "complexity_level": "Advanced"
        }
        
        print(f"📋 Kurs-Anfrage: {course_request['title']}")
        print(f"🎓 Zielgruppe: {course_request['target_audience']}")
        print(f"⏱️ Dauer: {course_request['duration']}")
        
        # Test durchführen
        result = self._run_test_workflow(course_request, "data_analysis_advanced")
        return result
    
    def _run_test_workflow(self, course_request, test_id):
        """
        Führt den kompletten Workflow für einen Test-Case durch
        """
        print(f"\n🚀 Starte Workflow für {test_id}...")
        
        start_time = datetime.now()
        
        try:
            # 1. Content Creation
            print("📝 Step 1: Content Creation...")
            # Erstelle instructions String aus course_request
            instructions = f"""
Zielgruppe: {course_request['target_audience']}
Dauer: {course_request['duration']}
Format: {course_request['format']}
Komplexität: {course_request['complexity_level']}

Lernziele:
""" + "\n".join(f"- {obj}" for obj in course_request['learning_objectives'])
            
            content_result = self.orchestrator.create_content(
                topic=course_request['title'],
                instructions=instructions
            )
            
            # 2. Didactic Optimization
            print("🎓 Step 2: Didactic Optimization...")
            didactic_result = self.orchestrator.optimize_didactics(
                content=content_result
            )
            
            # 3. Quality Assessment (Critical Thinker 2.0)
            print("🔍 Step 3: Quality Assessment...")
            quality_scores = self.quality_assessment.assess_content(didactic_result)
            
            # 4. Critical Review
            print("💭 Step 4: Critical Review...")
            review_result = self.orchestrator.critically_review(
                content=didactic_result
            )
            
            end_time = datetime.now()
            processing_time = (end_time - start_time).total_seconds()
            
            # Ergebnis zusammenfassen
            test_result = {
                "test_id": test_id,
                "course_request": course_request,
                "processing_time_seconds": processing_time,
                "quality_scores": quality_scores,
                "content_length": len(didactic_result),
                "critical_review": review_result,
                "timestamp": datetime.now().isoformat(),
                "status": "completed"
            }
            
            self.results.append(test_result)
            
            # Ergebnis anzeigen
            self._display_test_results(test_result)
            
            return test_result
            
        except Exception as e:
            error_result = {
                "test_id": test_id,
                "error": str(e),
                "status": "failed",
                "timestamp": datetime.now().isoformat()
            }
            self.results.append(error_result)
            print(f"❌ Test {test_id} fehlgeschlagen: {e}")
            return error_result
    
    def _display_test_results(self, result):
        """
        Zeigt die Test-Ergebnisse in übersichtlicher Form an
        """
        print(f"\n📊 ERGEBNISSE: {result['test_id']}")
        print("-" * 50)
        print(f"⏱️ Verarbeitungszeit: {result['processing_time_seconds']:.2f}s")
        print(f"📄 Content-Länge: {result['content_length']} Zeichen")
        
        if 'quality_scores' in result:
            scores = result['quality_scores']
            print(f"\n🎯 QUALITY SCORES:")
            
            # Handle nested structure from QualityAssessment.assess_content()
            if 'component_scores' in scores:
                components = scores['component_scores']
                print(f"   📖 Lesbarkeit: {components.get('readability', {}).get('score', 'N/A')}")
                print(f"   🏗️ Struktur: {components.get('structure', {}).get('score', 'N/A')}")
                print(f"   🔗 Konsistenz: {components.get('consistency', {}).get('score', 'N/A')}")
                print(f"   ⭐ Gesamt: {scores.get('overall_score', 'N/A')}")
            else:
                # Fallback for direct score structure
                print(f"   📖 Lesbarkeit: {scores.get('readability_score', 'N/A')}")
                print(f"   🏗️ Struktur: {scores.get('structure_score', 'N/A')}")
                print(f"   🔗 Konsistenz: {scores.get('consistency_score', 'N/A')}")
                print(f"   ⭐ Gesamt: {scores.get('overall_score', 'N/A')}")
        
        # Performance Check
        if result['processing_time_seconds'] > 90:
            print("⚠️ PERFORMANCE WARNING: >90s (Target: <90s)")
        else:
            print("✅ PERFORMANCE OK: <90s")
    
    def run_all_tests(self):
        """
        Führt alle Test-Cases aus und erstellt einen Summary-Report
        """
        print("🧪 STARTING TEST SUITE - Multi-Agenten-Kursgenerator")
        print("="*70)
        
        # Test Case 1
        result1 = self.test_case_1_marketing_beginner()
        
        # Test Case 2  
        result2 = self.test_case_2_data_analysis_advanced()
        
        # Summary Report
        self._generate_summary_report()
        
        return self.results
    
    def _generate_summary_report(self):
        """
        Erstellt einen Summary-Report aller Tests
        """
        print("\n📋 SUMMARY REPORT")
        print("="*50)
        
        successful_tests = [r for r in self.results if r['status'] == 'completed']
        failed_tests = [r for r in self.results if r['status'] == 'failed']
        
        print(f"✅ Erfolgreiche Tests: {len(successful_tests)}/{len(self.results)}")
        print(f"❌ Fehlgeschlagene Tests: {len(failed_tests)}/{len(self.results)}")
        
        if successful_tests:
            avg_time = sum(r['processing_time_seconds'] for r in successful_tests) / len(successful_tests)
            print(f"⏱️ Durchschnittliche Verarbeitungszeit: {avg_time:.2f}s")
            
            # Performance Check
            if avg_time <= 90:
                print("🎯 PERFORMANCE TARGET ERREICHT (<90s)")
            else:
                print("⚠️ PERFORMANCE TARGET VERFEHLT (>90s)")
        
        # Ergebnisse in JSON speichern
        self._save_results_to_file()
    
    def _save_results_to_file(self):
        """
        Speichert die Test-Ergebnisse in JSON-Datei
        """
        filename = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Ergebnisse gespeichert in: {filename}")

def main():
    """
    Hauptfunktion für Test-Ausführung
    """
    if len(sys.argv) > 1:
        test_case = sys.argv[1].lower()
        tester = TestUseCases()
        
        if test_case == "marketing":
            tester.test_case_1_marketing_beginner()
        elif test_case == "data":
            tester.test_case_2_data_analysis_advanced()
        elif test_case == "all":
            tester.run_all_tests()
        else:
            print("Usage: python test_use_cases.py [marketing|data|all]")
    else:
        # Default: Alle Tests ausführen
        tester = TestUseCases()
        tester.run_all_tests()

if __name__ == "__main__":
    main() 
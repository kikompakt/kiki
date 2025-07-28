"""
Quality Assessment für Intelligentes KI-Kursstudio
Automatisierte Bewertung von Kursinhalten mit datengestützten Metriken

Features:
- Strukturbewertung (Lernziele, Beispiele, Hierarchie)
- Didaktikbewertung (Verständlichkeit, Progression) 
- Konsistenzbewertung (Terminologie, Logik)
- Qualitäts-Gates für Production-Freigabe
- TYPE SAFETY: Umfassende Type-Hints für bessere Code-Qualität
"""

import re
import logging
from typing import Dict, List, Any, Tuple, Optional, Set
from collections import Counter
import statistics

logger = logging.getLogger(__name__)

class QualityAssessment:
    """
    Automatisierte Qualitätsbewertung für Kursinhalte
    
    Implementiert 4-Ebenen Framework:
    - Ebene 1: Automatisierte Metriken (diese Klasse)
    - Ebene 2: KI-Peer-Review (geplant)
    - Ebene 3: Human-in-the-Loop 2.0 (geplant)
    - Ebene 4: User-Feedback Loop (geplant)
    """
    
    def __init__(self):
        self.min_quality_threshold = 70.0  # Mindest-Score für Human Review
        self.weights = {
            'readability': 0.3,
            'structure': 0.4,
            'consistency': 0.3
        }
    
    def readability_score(self, text: str) -> Dict[str, Any]:
        """
        Berechnet Lesbarkeitsindex nach Flesch-Reading-Ease (angepasst für Deutsch)
        
        Returns:
            dict: {
                'score': float (0-100),
                'level': str,
                'details': dict
            }
        """
        if not text or len(text.strip()) < 50:
            return {
                'score': 0.0,
                'level': 'insufficient_text',
                'details': {'error': 'Text zu kurz für Analyse'}
            }
        
        # Text-Statistiken
        sentences = self._count_sentences(text)
        words = self._count_words(text)
        syllables = self._count_syllables_german(text)
        
        if sentences == 0 or words == 0:
            return {
                'score': 0.0,
                'level': 'invalid_text',
                'details': {'error': 'Unvollständiger Text'}
            }
        
        # Flesch-Reading-Ease (angepasst für Deutsch)
        avg_sentence_length = words / sentences
        avg_syllables_per_word = syllables / words
        
        # Deutsche Flesch-Formel (leicht angepasste Gewichtung)
        flesch_score = 180 - (avg_sentence_length * 1.0) - (avg_syllables_per_word * 58.5)
        
        # Normalisierung auf 0-100
        flesch_score = max(0, min(100, flesch_score))
        
        # Schwierigkeitsgrad bestimmen
        level = self._get_readability_level(flesch_score)
        
        return {
            'score': round(flesch_score, 1),
            'level': level,
            'details': {
                'sentences': sentences,
                'words': words,
                'syllables': syllables,
                'avg_sentence_length': round(avg_sentence_length, 1),
                'avg_syllables_per_word': round(avg_syllables_per_word, 1)
            }
        }
    
    def structure_check(self, content: str) -> Dict[str, Any]:
        """
        Prüft strukturelle Qualität des Kursinhalts
        
        Checks:
        - Lernziele vorhanden
        - Beispiele/Analogien
        - Logische Gliederung
        - Zusammenfassungen
        
        Returns:
            dict: {
                'score': float (0-100),
                'details': dict,
                'recommendations': list
            }
        """
        score_components = {}
        recommendations = []
        
        # 1. Lernziele-Check (25 Punkte)
        learning_objectives_score = self._check_learning_objectives(content)
        score_components['learning_objectives'] = learning_objectives_score
        
        if learning_objectives_score < 15:
            recommendations.append("Füge klare Lernziele hinzu (z.B. 'Nach dieser Lektion können Sie...')")
        
        # 2. Beispiele/Analogien-Check (25 Punkte)
        examples_score = self._check_examples(content)
        score_components['examples'] = examples_score
        
        if examples_score < 15:
            recommendations.append("Integriere mehr praktische Beispiele oder Analogien")
        
        # 3. Gliederung-Check (25 Punkte)
        structure_score = self._check_structure(content)
        score_components['structure'] = structure_score
        
        if structure_score < 15:
            recommendations.append("Verbessere die logische Gliederung mit Überschriften")
        
        # 4. Zusammenfassung-Check (25 Punkte)
        summary_score = self._check_summary(content)
        score_components['summary'] = summary_score
        
        if summary_score < 15:
            recommendations.append("Füge eine Zusammenfassung oder Key Takeaways hinzu")
        
        total_score = sum(score_components.values())
        
        return {
            'score': round(total_score, 1),
            'details': score_components,
            'recommendations': recommendations
        }
    
    def consistency_check(self, content: str) -> Dict[str, Any]:
        """
        Prüft Terminologie-Konsistenz und roten Faden
        
        Returns:
            dict: {
                'score': float (0-100),
                'details': dict,
                'issues': list
            }
        """
        issues = []
        score_components = {}
        
        # 1. Terminologie-Konsistenz (40 Punkte)
        terminology_score = self._check_terminology_consistency(content)
        score_components['terminology'] = terminology_score
        
        if terminology_score < 25:
            issues.append("Inkonsistente Verwendung von Fachbegriffen entdeckt")
        
        # 2. Stil-Konsistenz (30 Punkte)
        style_score = self._check_style_consistency(content)
        score_components['style'] = style_score
        
        if style_score < 20:
            issues.append("Uneinheitlicher Schreibstil (Du/Sie, Zeitformen)")
        
        # 3. Roter Faden (30 Punkte)
        coherence_score = self._check_coherence(content)
        score_components['coherence'] = coherence_score
        
        if coherence_score < 20:
            issues.append("Logischer Aufbau könnte verbessert werden")
        
        total_score = sum(score_components.values())
        
        return {
            'score': round(total_score, 1),
            'details': score_components,
            'issues': issues
        }
    
    def overall_quality_score(self, content: str) -> Dict[str, Any]:
        """
        Berechnet kombinierenden Qualitäts-Score
        
        Returns:
            dict: {
                'overall_score': float (0-100),
                'component_scores': dict,
                'quality_level': str,
                'ready_for_review': bool,
                'improvement_priority': list
            }
        """
        # Einzelbewertungen
        readability = self.readability_score(content)
        structure = self.structure_check(content)
        consistency = self.consistency_check(content)
        
        # Gewichteter Gesamtscore
        overall_score = (
            readability['score'] * self.weights['readability'] +
            structure['score'] * self.weights['structure'] +
            consistency['score'] * self.weights['consistency']
        )
        
        component_scores = {
            'readability': readability,
            'structure': structure,
            'consistency': consistency
        }
        
        # Qualitätslevel bestimmen
        quality_level = self._get_quality_level(overall_score)
        
        # Ready for Human Review?
        ready_for_review = overall_score >= self.min_quality_threshold
        
        # Verbesserungs-Prioritäten
        improvement_priority = self._get_improvement_priorities(component_scores)
        
        return {
            'overall_score': round(overall_score, 1),
            'component_scores': component_scores,
            'quality_level': quality_level,
            'ready_for_review': ready_for_review,
            'improvement_priority': improvement_priority,
            'threshold': self.min_quality_threshold
        }
    
    # === HELPER METHODS ===
    
    def _count_sentences(self, text: str) -> int:
        """Zählt Sätze im Text"""
        sentence_endings = re.findall(r'[.!?]+', text)
        return max(1, len(sentence_endings))
    
    def _count_words(self, text: str) -> int:
        """Zählt Wörter im Text"""
        words = re.findall(r'\b\w+\b', text)
        return len(words)
    
    def _count_syllables_german(self, text: str) -> int:
        """Approximiert Silben für deutsche Texte"""
        words = re.findall(r'\b\w+\b', text.lower())
        total_syllables = 0
        
        for word in words:
            # Einfache Heuristik für deutsche Silben
            vowel_groups = re.findall(r'[aeiouäöü]+', word)
            syllables = len(vowel_groups)
            
            # Mindestens 1 Silbe pro Wort
            total_syllables += max(1, syllables)
        
        return total_syllables
    
    def _get_readability_level(self, score: float) -> str:
        """Bestimmt Schwierigkeitsgrad basierend auf Flesch-Score"""
        if score >= 80:
            return "sehr_leicht"
        elif score >= 70:
            return "leicht"
        elif score >= 60:
            return "mittel"
        elif score >= 50:
            return "schwer"
        else:
            return "sehr_schwer"
    
    def _check_learning_objectives(self, content: str) -> float:
        """Prüft auf Lernziele (0-25 Punkte)"""
        learning_indicators = [
            r'nach dieser (lektion|einheit|kapitel)',
            r'sie (werden|können|lernen)',
            r'lernziel',
            r'am ende (dieser|dieses)',
            r'ziel dieser',
        ]
        
        score = 0
        content_lower = content.lower()
        
        for pattern in learning_indicators:
            if re.search(pattern, content_lower):
                score += 5
        
        return min(25, score)
    
    def _check_examples(self, content: str) -> float:
        """Prüft auf Beispiele/Analogien (0-25 Punkte)"""
        example_indicators = [
            r'beispiel',
            r'zum beispiel',
            r'z\.b\.',
            r'stellen sie sich vor',
            r'wie wenn',
            r'ähnlich wie',
            r'vergleichbar mit',
        ]
        
        score = 0
        content_lower = content.lower()
        
        found_patterns = 0
        for pattern in example_indicators:
            matches = len(re.findall(pattern, content_lower))
            if matches > 0:
                found_patterns += 1
                score += min(5, matches * 2)  # Max 5 Punkte pro Pattern-Typ
        
        return min(25, score)
    
    def _check_structure(self, content: str) -> float:
        """Prüft logische Gliederung (0-25 Punkte)"""
        score = 0
        
        # Überschriften
        headers = re.findall(r'^#{1,3}\s+.+$', content, re.MULTILINE)
        score += min(10, len(headers) * 2)
        
        # Listen/Aufzählungen
        lists = re.findall(r'^\s*[-*+]\s+', content, re.MULTILINE)
        score += min(5, len(lists))
        
        # Nummerierte Listen
        numbered = re.findall(r'^\s*\d+\.\s+', content, re.MULTILINE)
        score += min(5, len(numbered))
        
        # Absätze (mindestens 3 für gute Struktur)
        paragraphs = content.split('\n\n')
        if len(paragraphs) >= 3:
            score += 5
        
        return min(25, score)
    
    def _check_summary(self, content: str) -> float:
        """Prüft auf Zusammenfassung (0-25 Punkte)"""
        summary_indicators = [
            r'zusammenfassung',
            r'fazit',
            r'key takeaways',
            r'wichtigste punkte',
            r'merken sie sich',
            r'in dieser lektion haben',
        ]
        
        score = 0
        content_lower = content.lower()
        
        for pattern in summary_indicators:
            if re.search(pattern, content_lower):
                score += 8
        
        return min(25, score)
    
    def _check_terminology_consistency(self, content: str) -> float:
        """Prüft Terminologie-Konsistenz (0-40 Punkte)"""
        # Einfache Heuristik: Suche nach Fachbegriffen und deren einheitlicher Verwendung
        
        # Extrahiere potenzielle Fachbegriffe (Wörter mit Großbuchstaben)
        technical_terms = re.findall(r'\b[A-ZÄÖÜ][a-zäöüß]+(?:[A-ZÄÖÜ][a-zäöüß]*)*\b', content)
        
        if not technical_terms:
            return 40  # Keine Fachbegriffe = keine Inkonsistenz
        
        # Zähle Verwendung
        term_counts = Counter(technical_terms)
        
        # Bewerte Konsistenz (vereinfachte Heuristik)
        consistency_ratio = len(set(technical_terms)) / len(technical_terms) if technical_terms else 1
        
        # Je niedriger die Ratio, desto konsistenter
        score = 40 * (1 - min(0.5, consistency_ratio))
        
        return max(20, score)  # Minimum 20 Punkte
    
    def _check_style_consistency(self, content: str) -> float:
        """Prüft Stil-Konsistenz (0-30 Punkte)"""
        score = 30
        
        # Du vs Sie Konsistenz
        du_count = len(re.findall(r'\b(du|dich|dir|dein)\b', content, re.IGNORECASE))
        sie_count = len(re.findall(r'\bsie\b', content, re.IGNORECASE))
        
        if du_count > 0 and sie_count > 0:
            score -= 10  # Mischung von Du/Sie
        
        # Zeitformen-Konsistenz (vereinfacht)
        present_tense = len(re.findall(r'\b(ist|sind|haben|werden)\b', content))
        past_tense = len(re.findall(r'\b(war|waren|hatten|wurden)\b', content))
        
        if present_tense > 0 and past_tense > present_tense * 0.3:
            score -= 5  # Zu viel Vergangenheit in Lehrtext
        
        return max(15, score)
    
    def _check_coherence(self, content: str) -> float:
        """Prüft logischen Zusammenhang (0-30 Punkte)"""
        score = 30
        
        # Übergangswörter
        transition_words = [
            r'jedoch', r'aber', r'dennoch', r'trotzdem',
            r'außerdem', r'darüber hinaus', r'zusätzlich',
            r'deshalb', r'daher', r'folglich',
            r'zunächst', r'danach', r'schließlich',
        ]
        
        transition_count = 0
        for pattern in transition_words:
            transition_count += len(re.findall(pattern, content, re.IGNORECASE))
        
        # Bewerte basierend auf Text-Länge
        words = self._count_words(content)
        expected_transitions = words / 100  # Etwa 1 Übergangswort pro 100 Wörter
        
        if transition_count >= expected_transitions * 0.5:
            score = 30
        else:
            score = max(15, transition_count / expected_transitions * 30)
        
        return score
    
    def _get_quality_level(self, score: float) -> str:
        """Bestimmt Qualitätslevel"""
        if score >= 90:
            return "excellent"
        elif score >= 80:
            return "good"
        elif score >= 70:
            return "acceptable"
        elif score >= 60:
            return "needs_improvement"
        else:
            return "poor"
    
    def _get_improvement_priorities(self, component_scores: Dict) -> List[str]:
        """Bestimmt Verbesserungs-Prioritäten"""
        priorities = []
        
        scores = {
            'readability': component_scores['readability']['score'],
            'structure': component_scores['structure']['score'],
            'consistency': component_scores['consistency']['score']
        }
        
        # Sortiere nach niedrigsten Scores
        sorted_components = sorted(scores.items(), key=lambda x: x[1])
        
        for component, score in sorted_components:
            if score < 70:
                if component == 'readability':
                    priorities.append("Vereinfache Sprache und Satzstruktur")
                elif component == 'structure':
                    priorities.append("Verbessere Gliederung und füge mehr Beispiele hinzu")
                elif component == 'consistency':
                    priorities.append("Achte auf einheitliche Terminologie und Stil")
        
        return priorities[:3]  # Max 3 Prioritäten

    def assess(self, content: str) -> Dict[str, Any]:
        """
        Wrapper method für Test-Integration - verwendet overall_quality_score
        
        Args:
            content: Kursinhalt als String
            
        Returns:
            Vollständige Qualitätsbewertung mit allen Metriken
        """
        return self.overall_quality_score(content)


# === INTEGRATION HELPER ===

def assess_course_quality(content: str) -> Dict[str, Any]:
    """
    Hauptfunktion für automatisierte Kursbewertung
    
    Args:
        content: Der zu bewertende Kursinhalt
        
    Returns:
        Dictionary mit Bewertungsresultaten und Metriken
    """
    try:
        if not content or not content.strip():
            return _create_empty_assessment()
        
        quality_assessment = QualityAssessment()
        return quality_assessment.assess(content)
        
    except Exception as e:
        logger.error(f"Quality assessment error: {e}")
        return _create_empty_assessment()

def _create_empty_assessment() -> Dict[str, Any]:
    """Erstellt leere Assessment-Struktur für Error-Cases"""
    return {
        'overall_score': 0.0,
        'quality_level': 'UNASSESSABLE',
        'ready_for_review': False,
        'threshold': 7.0,
        'component_scores': {
            'readability': {'score': 0, 'level': 'POOR'},
            'structure': {'score': 0, 'level': 'POOR', 'details': {}, 'recommendations': []},
            'consistency': {'score': 0, 'level': 'POOR', 'issues': []}
        },
        'improvement_priority': []
    }


if __name__ == "__main__":
    # Test der Implementierung
    test_content = """
    # Einführung in Python

    ## Lernziele
    Nach dieser Lektion können Sie grundlegende Python-Syntax verstehen und einfache Programme schreiben.

    ## Was ist Python?
    Python ist eine Programmiersprache. Sie ist einfach zu lernen und vielseitig einsetzbar.

    Zum Beispiel können Sie mit Python Websites erstellen, Daten analysieren oder künstliche Intelligenz entwickeln.

    ## Grundlagen
    
    - Variablen speichern Daten
    - Funktionen führen Aktionen aus
    - Schleifen wiederholen Code

    ## Zusammenfassung
    Python ist eine mächtige, aber einfache Programmiersprache für Anfänger.
    """
    
    assessor = QualityAssessment()
    result = assessor.overall_quality_score(test_content)
    
    print("=== QUALITY ASSESSMENT TEST ===")
    print(f"Gesamtscore: {result['overall_score']}/100")
    print(f"Qualitätslevel: {result['quality_level']}")
    print(f"Ready for Review: {result['ready_for_review']}")
    print("\nKomponenten:")
    for component, data in result['component_scores'].items():
        print(f"  {component}: {data['score']}/100") 
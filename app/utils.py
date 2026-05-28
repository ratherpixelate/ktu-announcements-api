import math
import re
from datetime import date

KNOWN_SCHEMES = [2015, 2019, 2024]

def get_scheme_for_admission(adm_year: int) -> str:
    """Finds the highest scheme that is <= the admission year."""
    valid_schemes = [s for s in KNOWN_SCHEMES if s <= adm_year]
    return str(max(valid_schemes)) if valid_schemes else "2015"

def extract_schemes(publish_date: date, text: str) -> list[str]:
    """Smart parser to determine the KTU scheme based on keywords and math."""
    text_lower = text.lower()
    
    # PHASE 1: Explicit Keywords
    found_schemes = re.findall(r'(20\d{2})\s*scheme', text_lower)
    found_admissions = re.findall(r'(20\d{2})\s*admission', text_lower)
    
    explicit_years = set(int(y) for y in found_schemes + found_admissions)
    
    schemes_result = set()
    for y in explicit_years:
        if y in KNOWN_SCHEMES:
             schemes_result.add(str(y))
        else:
             schemes_result.add(get_scheme_for_admission(y))
             
    if schemes_result:
        return list(schemes_result)

    # PHASE 1.5: General Announcement Detector
    degree_keywords = ['b.tech', 'm.tech', 'b.arch', 'm.arch', 'mca', 'mba', 'phd']
    semester_keywords = [f's{i}' for i in range(1, 9)]
    
    has_degree = any(deg in text_lower for deg in degree_keywords)
    has_semester = any(sem in text_lower for sem in semester_keywords)
    
    if not has_degree and not has_semester:
        return ["General"]

    # PHASE 2: Safety Check (Abort math for weird cases)
    safety_words = ['supplementary', 'supply', 'mercy chance', 'part time', '(pt)']
    if any(word in text_lower for word in safety_words):
        return [] 

    # PHASE 3: The Mathematical Calculation (For B.Tech)
    is_btech = 'b.tech' in text_lower
    is_inter_college_transfer = 'inter-college transfer' in text_lower or 'inter college transfer' in text_lower

    if is_btech or is_inter_college_transfer:
        sem_match = re.search(r's([1-8])', text_lower)
        if sem_match:
            sem = int(sem_match.group(1))

            # Try to extract AY start year from text (e.g. "AY 2026-2027", "AY 2026-27")
            ay_match = re.search(r'\bay\b\s*(\d{4})-(\d{2,4})', text_lower)
            if ay_match:
                ay_start_year = int(ay_match.group(1))
                year_of_study = math.ceil(sem / 2)
                admission_year = ay_start_year - year_of_study + 1
            else:
                pub_year = publish_date.year
                pub_month = publish_date.month
                
                # Determine Academic Start Year based on Odd/Even and Month
                if sem % 2 != 0:  # Odd (1, 3, 5, 7)
                    start_year = pub_year - 1 if pub_month <= 6 else pub_year
                else:  # Even (2, 4, 6, 8)
                    start_year = pub_year - 1 if pub_month <= 9 else pub_year
                    
                year_of_study = math.ceil(sem / 2)
                admission_year = start_year - year_of_study + 1
            
            return [get_scheme_for_admission(admission_year)]
            
    return []
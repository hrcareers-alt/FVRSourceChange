import os
import json
import time
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

# --- CONFIGURATION ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1cm89p7-81Z394q8oDFRk0ZNi3nBgFSbEbcZsUMUaqDs/edit"
TARGET_SOURCE = "XRP EDWARD BELACSE"

# --- LOCATION MAPPING ---
FVR_LINKS = {
    "cebu": "https://jobs.foundever.com/job/Cebu-Cebu-Customer-Service-Associate-Phil/1345433100/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "cebu robinson": "https://jobs.foundever.com/job-invite/406350/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "tarlac": "https://jobs.foundever.com/job/Tarlac-Tarlac-Customer-Service-Associate-Phil/1345432700/?utm_source=SourcingOther&utm_campaign=EBELACSE",
    "pasig": "https://jobs.foundever.com/job-invite/406345/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "mandaluyong shaw": "https://jobs.foundever.com/job-invite/406345/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "mandaluyong edsa": "https://jobs.foundever.com/job-invite/406345/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "palawan": "https://jobs.foundever.com/job-invite/406352/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "makati": "https://jobs.foundever.com/job-invite/406349/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "baguio": "https://jobs.foundever.com/job/Baguio-Baguio-Customer-Service-Associate-Phil/1345433200/?utm_source=customcampaign&utm_campaign=NERP%20EBELACSE",
    "alabang": "https://jobs.foundever.com/job-invite/406346/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "quezon": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "manila-ncr": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff"
}

def setup_gspread():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    json_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if json_creds:
        creds_dict = json.loads(json_creds)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return gspread.authorize(creds)

def get_mapped_url(location_str):
    loc = str(location_str).lower().strip()
    if not loc or loc == "n/a":
        return None
    
    # Priority check for specific sub-sites
    if "cebu robinson" in loc: return FVR_LINKS["cebu robinson"]
    if "mandaluyong edsa" in loc: return FVR_LINKS["mandaluyong edsa"]
    if "mandaluyong shaw" in loc: return FVR_LINKS["mandaluyong shaw"]
    
    # General region matching
    for key, url in FVR_LINKS.items():
        if key in loc:
            return url
    
    return None

def find_column_by_header(headers, search_terms):
    for idx, h in enumerate(headers):
        h_lower = str(h).lower()
        if any(term in h_lower for term in search_terms):
            return idx
    return None

def process_fvr_source_changes():
    gc = setup_gspread()
    doc = gc.open_by_url(SHEET_URL)
    worksheets = doc.worksheets()
    
    # Run-level Logging & Reconciliation tracking
    stats = {
        "tabs_inspected": len(worksheets), "tabs_with_target": 0, "eligible_rows": 0,
        "success_changed": 0, "already_correct": 0, "no_prefilled": 0, "invalid": 0,
        "exceptions": 0, "skipped": 0
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Using a persistent context to manage Maki sessions safely
        context = browser.new_context(viewport={'width': 1280, 'height': 800})

        for ws in worksheets:
            try:
                data = ws.get_all_values()
            except Exception as e:
                print(f"Error reading {ws.title}: {e}")
                continue
                
            if not data: continue
            
            headers = data[0]
            
            # Identify required columns dynamically per worksheet
            status_col = find_column_by_header(headers, ["fvr source change"])
            if status_col is None:
                continue
                
            stats["tabs_with_target"] += 1
            
            first_col = find_column_by_header(headers, ["first name", "first"])
            last_col = find_column_by_header(headers, ["last name", "last"])
            email_col = find_column_by_header(headers, ["email"])
            loc_col = find_column_by_header(headers, ["location", "city"])

            if None in [first_col, last_col, email_col, loc_col]:
                print(f"[{ws.title}] Missing required data columns. Skipping sheet.")
                continue

            for row_idx, row in enumerate(data[1:], start=2):
                if len(row) <= status_col:
                    row.extend([""] * (status_col - len(row) + 1))
                
                status_val = str(row[status_col]).strip()
                
                # Rule 3: Do not process a row that already contains a status
                if status_val:
                    stats["skipped"] += 1
                    continue
                
                stats["eligible_rows"] += 1
                
                first_name = row[first_col].strip() if len(row) > first_col else ""
                last_name = row[last_col].strip() if len(row) > last_col else ""
                email = row[email_col].strip() if len(row) > email_col else ""
                location = row[loc_col].strip() if len(row) > loc_col else ""
                
                # Validation checks
                if not first_name or not last_name or not email or "@" not in email:
                    stats["exceptions"] += 1
                    print(f"[{ws.title} Row {row_idx}] Exception: Missing/Bad name or email.")
                    continue
                    
                loc_lower = location.lower()
                if "n/a" in loc_lower or "abroad" in loc_lower or loc_lower in ["dubai", "uae", "singapore", "usa", "zimbabwe"]:
                    ws.update_cell(row_idx, status_col + 1, "INVALID")
                    stats["invalid"] += 1
                    continue
                
                job_url = get_mapped_url(location)
                if not job_url:
                    stats["exceptions"] += 1
                    print(f"[{ws.title} Row {row_idx}] Exception: Unmapped location '{location}'")
                    continue

                # Process Application Flow
                page = context.new_page()
                try:
                    # 1. Access Foundever
                    page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
                    
                    # 2. Navigate to Maki
                    try:
                        take_assessment_btn = page.locator("a:has-text('Take the assessment'), button:has-text('Take the assessment')").first
                        take_assessment_btn.wait_for(state="visible", timeout=10000)
                        
                        # Handle popups or redirects by tracking new pages
                        with context.expect_page() as new_page_info:
                            take_assessment_btn.click()
                        maki_page = new_page_info.value
                    except PlaywrightTimeoutError:
                        print(f"[{ws.title} Row {row_idx}] Exception: 'Take the assessment' button missing.")
                        stats["exceptions"] += 1
                        continue

                    # Switch execution to the Maki page
                    maki_page.wait_for_load_state("networkidle")
                    
                    # 3. Enter Look-up Details
                    # NOTE: Selectors must be adapted to Maki's exact input field IDs/names
                    maki_page.locator("input[name*='first']").fill(first_name)
                    maki_page.locator("input[name*='last']").fill(last_name)
                    maki_page.locator("input[name*='email']").fill(email)
                    
                    maki_page.locator("button[type='submit'], button:has-text('Next'), button:has-text('Continue')").click()
                    maki_page.wait_for_load_state("networkidle")

                    # 4. Determine Prefilled Application State
                    # If Maki asks for standard application questions (e.g. source, referral) it's prefilled.
                    # If it's a completely blank profile build, it's a new app.
                    
                    source_input = maki_page.locator("input[name*='source'], input[name*='referral'], input:has-text('Employee name')")
                    
                    if source_input.count() == 0:
                        # Ensure we aren't in a direct-to-assessment flow (Invalid)
                        if maki_page.locator("text='Start Assessment'").count() > 0:
                            ws.update_cell(row_idx, status_col + 1, "INVALID")
                            stats["invalid"] += 1
                        else:
                            ws.update_cell(row_idx, status_col + 1, "EXECUTIVE TEAM / N")
                            stats["no_prefilled"] += 1
                        
                        maki_page.close()
                        continue
                    
                    # 5. Check and Correct Source
                    current_source = source_input.input_value()
                    
                    if current_source.strip().upper() == TARGET_SOURCE:
                        ws.update_cell(row_idx, status_col + 1, "EXECUTIVE TEAM / E")
                        stats["already_correct"] += 1
                    else:
                        source_input.fill(TARGET_SOURCE)
                        maki_page.locator("button:has-text('NEXT'), button:has-text('Save'), button:has-text('Submit')").first.click()
                        
                        # Wait for confirmation before starting any assessment
                        maki_page.wait_for_load_state("networkidle")
                        
                        # Re-verify the cell before updating to avoid race conditions
                        current_status = ws.cell(row_idx, status_col + 1).value
                        if not current_status:
                            ws.update_cell(row_idx, status_col + 1, "EXECUTIVE TEAM / Y")
                            stats["success_changed"] += 1
                        else:
                            print(f"[{ws.title} Row {row_idx}] Cell was modified by another process. Aborting write.")

                    # CRITICAL: Exit before assessment activities begin.
                    maki_page.close()
                    
                except Exception as e:
                    print(f"[{ws.title} Row {row_idx}] Exception during processing: {e}")
                    stats["exceptions"] += 1
                finally:
                    if not page.is_closed():
                        page.close()

        browser.close()
    
    # --- END-OF-RUN RECONCILIATION REPORT ---
    print("\n--- FOUNDEVER SOURCE CHANGE RECONCILIATION REPORT ---")
    for key, val in stats.items():
        print(f"{key.replace('_', ' ').title()}: {val}")
    print("-----------------------------------------------------")

if __name__ == "__main__":
    process_fvr_source_changes()

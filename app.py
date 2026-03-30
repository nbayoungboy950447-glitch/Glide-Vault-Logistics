import os
import json
import random
import string
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'glidevault_secret_2024')

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
SHEET_NAME = os.environ.get('SHEET_NAME', 'GlideVaultLogistics')

HEADERS = [
    'tracking_number', 'freight_type', 'status', 'sender_name', 'sender_address',
    'receiver_name', 'receiver_address', 'origin', 'destination', 'weight',
    'description', 'created_date', 'estimated_delivery', 'current_location',
    'notes', 'photo_url1', 'photo_url2', 'photo_url3', 'timeline_json',
    'hold_type', 'hold_amount', 'hold_message', 'hold_reference', 'hold_deadline'
]

STATUS_OPTIONS = [
    'Order Placed', 'Picked Up', 'In Transit',
    'Customs Clearance', 'Out for Delivery', 'Delivered', 'On Hold', 'Cleared'
]

import time as _time
_cached_sheet = None
_cache_ts = 0

def get_sheet():
    global _cached_sheet, _cache_ts
    if _cached_sheet and (_time.time() - _cache_ts) < 30:
        return _cached_sheet
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)
    sheet = spreadsheet.sheet1
    if sheet.row_values(1) != HEADERS:
        sheet.insert_row(HEADERS, 1)
    _cached_sheet = sheet
    _cache_ts = _time.time()
    return sheet

def generate_tracking_number():
    timestamp = datetime.now().strftime('%y%m%d')
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"GVL{timestamp}{random_part}"

def get_all_shipments():
    sheet = get_sheet()
    return sheet.get_all_records()

def get_shipment(tracking_number):
    sheet = get_sheet()
    records = sheet.get_all_records()
    for record in records:
        if record['tracking_number'].upper() == tracking_number.upper():
            return record
    return None

def find_row(tracking_number):
    sheet = get_sheet()
    col = sheet.col_values(1)
    for i, val in enumerate(col):
        if val.upper() == tracking_number.upper():
            return i + 1
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/track', methods=['GET', 'POST'])
def track():
    if request.method == 'POST':
        tracking_number = request.form.get('tracking_number', '').strip()
        if tracking_number:
            return redirect(url_for('shipment_detail', tracking_number=tracking_number.upper()))
        flash('Please enter a tracking number.', 'error')
    return render_template('track.html')

@app.route('/shipment/<tracking_number>')
def shipment_detail(tracking_number):
    shipment = get_shipment(tracking_number)
    if not shipment:
        return render_template('not_found.html', tracking_number=tracking_number)
    timeline = []
    try:
        timeline = json.loads(shipment.get('timeline_json', '[]'))
    except Exception:
        pass
    photos = [shipment.get('photo_url1',''), shipment.get('photo_url2',''), shipment.get('photo_url3','')]
    photos = [p for p in photos if p]
    return render_template('shipment_detail.html', shipment=shipment, timeline=timeline, photos=photos)

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin'):
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Incorrect password.', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    shipments = get_all_shipments()
    return render_template('admin_dashboard.html', shipments=shipments, status_options=STATUS_OPTIONS)

@app.route('/admin/create', methods=['GET', 'POST'])
def admin_create():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        tracking_number = generate_tracking_number()
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        initial_timeline = json.dumps([
            {"port": request.form.get('origin','').strip(), "completed": True, "events": [
                {"name": "Order Placed", "timestamp": now, "note": "Shipment created"}
            ]}
        ])
        row = [
            tracking_number,
            request.form.get('freight_type','Air Freight'),
            'Order Placed',
            request.form.get('sender_name',''),
            request.form.get('sender_address',''),
            request.form.get('receiver_name',''),
            request.form.get('receiver_address',''),
            request.form.get('origin',''),
            request.form.get('destination',''),
            request.form.get('weight',''),
            request.form.get('description',''),
            now,
            request.form.get('estimated_delivery',''),
            request.form.get('origin',''),
            request.form.get('notes',''),
            request.form.get('photo_url1',''),
            request.form.get('photo_url2',''),
            request.form.get('photo_url3',''),
            initial_timeline
        ]
        sheet = get_sheet()
        sheet.append_row(row)
        flash(f'Shipment created! Tracking: {tracking_number}', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_shipment_form.html', shipment=None, status_options=STATUS_OPTIONS, mode='create')

@app.route('/admin/edit/<tracking_number>', methods=['GET', 'POST'])
def admin_edit(tracking_number):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    shipment = get_shipment(tracking_number)
    if not shipment:
        flash('Shipment not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        row_num = find_row(tracking_number)
        sheet = get_sheet()
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        new_status = request.form.get('status', shipment['status'])
        try:
            timeline = json.loads(shipment.get('timeline_json', '[]'))
        except Exception:
            timeline = []

        # Handle new port-based timeline event
        new_port = request.form.get('new_port', '').strip()
        new_event_name = request.form.get('new_event_name', '').strip()
        new_event_time = request.form.get('new_event_time', now).strip()
        new_event_note = request.form.get('new_event_note', '').strip()
        port_completed = request.form.get('port_completed', 'true') == 'true'

        if new_port and new_event_name:
            # Check if timeline uses new port format
            if timeline and isinstance(timeline[0], dict) and 'port' in timeline[0]:
                # New format - find or create port
                port_found = False
                for stop in timeline:
                    if stop['port'].strip().lower().replace(',', '') == new_port.strip().lower().replace(',', ''):
                        stop['events'].append({
                            "name": new_event_name,
                            "timestamp": new_event_time,
                            "note": new_event_note
                        })
                        stop['completed'] = port_completed
                        port_found = True
                        break
                if not port_found:
                    timeline.append({
                        "port": new_port,
                        "completed": port_completed,
                        "events": [{"name": new_event_name, "timestamp": new_event_time, "note": new_event_note}]
                    })
            else:
                # Convert old format or start new
                new_tl = []
                if timeline:
                    # Convert old events into first port
                    old_port = timeline[0].get('location', 'Origin') if timeline else 'Origin'
                    old_events = [{"name": e.get('status',''), "timestamp": e.get('timestamp',''), "note": e.get('note','')} for e in timeline]
                    new_tl.append({"port": old_port, "completed": True, "events": old_events})
                new_tl.append({
                    "port": new_port,
                    "completed": port_completed,
                    "events": [{"name": new_event_name, "timestamp": new_event_time, "note": new_event_note}]
                })
                timeline = new_tl
        elif new_status != shipment['status']:
            # Old style status change
            if timeline and isinstance(timeline[0], dict) and 'port' in timeline[0]:
                loc = request.form.get('current_location', '')
                port_found = False
                for stop in timeline:
                    if ''.join(stop['port'].lower().split()) == ''.join(loc.lower().split()):
                        stop['events'].append({"name": new_status, "timestamp": now, "note": request.form.get('status_note','')})
                        port_found = True
                        break
                if not port_found and loc:
                    loc = loc.strip()
                    timeline.append({"port": loc, "completed": False, "events": [{"name": new_status, "timestamp": now, "note": request.form.get('status_note','')}]})
                    shipment['current_location'] = loc
            else:
                timeline.append({"status": new_status, "location": request.form.get('current_location',''), "timestamp": now, "note": request.form.get('status_note','')})
        updated_row = [
            tracking_number,
            request.form.get('freight_type', shipment['freight_type']),
            new_status,
            request.form.get('sender_name', shipment['sender_name']),
            request.form.get('sender_address', shipment['sender_address']),
            request.form.get('receiver_name', shipment['receiver_name']),
            request.form.get('receiver_address', shipment['receiver_address']),
            request.form.get('origin', shipment['origin']),
            request.form.get('destination', shipment['destination']),
            request.form.get('weight', shipment['weight']),
            request.form.get('description', shipment['description']),
            shipment['created_date'],
            request.form.get('estimated_delivery', shipment['estimated_delivery']),
            request.form.get('current_location', shipment['current_location']).title() if request.form.get('current_location') else shipment['current_location'],
            request.form.get('notes', shipment['notes']),
            request.form.get('photo_url1', shipment['photo_url1']),
            request.form.get('photo_url2', shipment['photo_url2']),
            request.form.get('photo_url3', shipment['photo_url3']),
            json.dumps(timeline),
            request.form.get('hold_type', shipment.get('hold_type', '')),
            request.form.get('hold_amount', shipment.get('hold_amount', '')),
            request.form.get('hold_message', shipment.get('hold_message', '')),
            request.form.get('hold_reference', shipment.get('hold_reference', '')),
            request.form.get('hold_deadline', shipment.get('hold_deadline', ''))
        ]
        sheet.update(f'A{row_num}:X{row_num}', [updated_row])
        flash('Shipment updated!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_shipment_form.html', shipment=shipment, status_options=STATUS_OPTIONS, mode='edit')

@app.route('/admin/delete/<tracking_number>', methods=['POST'])
def admin_delete(tracking_number):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    row_num = find_row(tracking_number)
    if row_num:
        get_sheet().delete_rows(row_num)
        flash('Shipment deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


# ── Footer Pages ──────────────────────────────────────────
@app.route('/services/air-freight')
def air_freight():
    return render_template('pages/air_freight.html')

@app.route('/services/ocean-freight')
def ocean_freight():
    return render_template('pages/ocean_freight.html')

@app.route('/services/railway-freight')
def railway_freight():
    return render_template('pages/railway_freight.html')

@app.route('/services/warehousing')
def warehousing():
    return render_template('pages/warehousing.html')

@app.route('/services/distribution')
def distribution():
    return render_template('pages/distribution.html')

@app.route('/services/value-added')
def value_added():
    return render_template('pages/value_added.html')

@app.route('/company/mission')
def mission():
    return render_template('pages/mission.html')

@app.route('/company/why-us')
def why_us():
    return render_template('pages/why_us.html')

@app.route('/company/case-studies')
def case_studies():
    return render_template('pages/case_studies.html')

@app.route('/company/certificates')
def certificates():
    return render_template('pages/certificates.html')

@app.route('/company/contact')
def contact():
    return render_template('pages/contact.html')

@app.route('/industries/global-coverage')
def global_coverage():
    return render_template('pages/global_coverage.html')

@app.route('/industries/distribution')
def industries_distribution():
    return render_template('pages/industries_distribution.html')

@app.route('/industries/accounting')
def accounting():
    return render_template('pages/accounting.html')

@app.route('/industries/freight-recovery')
def freight_recovery():
    return render_template('pages/freight_recovery.html')

@app.route('/industries/supply-chain')
def supply_chain():
    return render_template('pages/supply_chain.html')

@app.route('/industries/warehousing')
def industries_warehousing():
    return render_template('pages/industries_warehousing.html')

@app.route('/contact', methods=['POST'])
def contact_form():
    flash('Thank you! We will get back to you within 24 hours.', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)

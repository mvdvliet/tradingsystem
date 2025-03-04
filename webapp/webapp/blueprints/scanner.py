# blueprints/scanner.py
from flask import Blueprint, render_template, request, current_app
import logging
import requests
from auth_utils import check_authentication  # Import from auth_utils instead of dashboard

logger = logging.getLogger('webapp logger')

scanner_bp = Blueprint('scanner', __name__)

@scanner_bp.route("/")
@check_authentication()
def scanner():
    try:
        # Get the IBKR client from app config within the request context
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        base_url = current_app.config.get('IBKR_BASE_URL')
        
        # Get scanner parameters
        params = ibkr_client.get_scanner_parameters()
        
        if not params:
            logger.error("Failed to retrieve scanner parameters")
            return "Failed to retrieve scanner parameters.", 500

        scanner_map = {}
        filter_map = {}

        for item in params['instrument_list']:
            scanner_map[item['type']] = {
                "display_name": item['display_name'],
                "filters": item['filters'],
                "sorts": []
            }

        for item in params['filter_list']:
            filter_map[item['group']] = {
                "display_name": item['display_name'],
                "type": item['type'],
                "code": item['code']
            }

        for item in params['scan_type_list']:
            for instrument in item['instruments']:
                scanner_map[instrument]['sorts'].append({
                    "name": item['display_name'],
                    "code": item['code']
                })

        for item in params['location_tree']:
            scanner_map[item['type']]['locations'] = item['locations']

        submitted = request.args.get("submitted", "")
        selected_instrument = request.args.get("instrument", "STOCK.HK")
        location = request.args.get("location", "STK.HK.SEHK")
        sort = request.args.get("sort", "HOT_BY_VOLUME")
        filter_code = request.args.get("filter", "HOT_FILTER_TOP_PERC_GAIN")
        scan_results = []
        
        # Validate filter_value
        try:
            filter_value = int(request.args.get("filter_value", 5))
            if filter_value <= 0:
                filter_value = 5
                logger.warning("Invalid filter value (must be positive), using default: 5")
        except ValueError:
            filter_value = 5
            logger.warning("Invalid filter value (must be a number), using default: 5")

        if submitted:
            logger.info("Submitting scanner request")
            data = {
                "instrument": selected_instrument,
                "location": location,
                "type": sort,
                "filter": [
                    {
                        "code": filter_code,
                        "value": filter_value
                    }
                ]
            }
                
            scan_results = ibkr_client.run_scanner(data)
            
            if not scan_results:
                logger.error("Failed to run scanner")
                return "Failed to run scanner.", 500

        return render_template("scanner.html", params=params, scanner_map=scanner_map, filter_map=filter_map, scan_results=scan_results)
    except Exception as e:
        logger.error(f"Error in scanner route: {e}")
        return "Error loading scanner.", 500
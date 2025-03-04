# blueprints/pnl.py
from flask import Blueprint, render_template, current_app
from markupsafe import Markup
import logging
import pandas as pd
import plotly.graph_objs as go
from plotly.io import to_html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from models import PNL
from auth_utils import check_authentication

logger = logging.getLogger('webapp logger')

pnl_bp = Blueprint('pnl', __name__)

@pnl_bp.route("/")
@check_authentication()
def pnl():
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Get the IBKR client from app config
            ibkr_client = current_app.config.get('IBKR_CLIENT')
            
            # Get PNL data
            pnl_data_raw = ibkr_client.get_pnl()
            
            if not pnl_data_raw:
                logger.error("Failed to retrieve PNL data")
                retry_count += 1
                if retry_count < max_retries:
                    logger.info(f"Retrying PNL data retrieval (attempt {retry_count+1}/{max_retries})")
                    continue
                return "Error retrieving PNL data.", 500
            
            # Log the raw PNL data structure for debugging
            logger.info(f"Raw PNL data keys: {pnl_data_raw.keys()}")
            logger.debug(f"Raw PNL data: {pnl_data_raw}")
            
            # Process pnl_data_raw to extract the required metrics
            try:
                # Extract PNL metrics using the client's helper method
                metrics = ibkr_client.extract_pnl_metrics(pnl_data_raw)
                
                if not metrics:
                    logger.error("Failed to extract PNL metrics")
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.info(f"Retrying PNL metrics extraction (attempt {retry_count+1}/{max_retries})")
                        continue
                    return "Error processing PNL data.", 500
                    
                pnl_data = {
                    'dpl': metrics['dpl'],
                    'nl': metrics['nl'],
                    'upl': metrics['upl'],
                    'el': metrics.get('el', 0.0),
                    'uel': metrics['uel'],
                    'mv': metrics['mv'],
                    'timestamp': datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Hong_Kong')).strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # If we got here, we have successfully retrieved and processed the data
                break
                
            except Exception as err:
                logger.error(f"Error processing PNL data: {err}")
                retry_count += 1
                if retry_count < max_retries:
                    logger.info(f"Retrying after error in PNL processing (attempt {retry_count+1}/{max_retries})")
                    continue
                return "Error processing PNL data.", 500

        except Exception as e:
            logger.error(f"Error in PNL data retrieval: {e}")
            retry_count += 1
            if retry_count < max_retries:
                logger.info(f"Retrying after general error (attempt {retry_count+1}/{max_retries})")
                continue
            return "Error retrieving PNL data.", 500
    
    # Proceed to fetch historical PNL data from the database
    try:
        # Query PNL data from the database
        pnls = PNL.query.order_by(PNL.timestamp).all()

        # Convert data to a DataFrame
        data = [
            {
                'timestamp': pnl.timestamp,
                'dpl': pnl.dpl,
                'nl': pnl.nl,
                'upl': pnl.upl,
                'el': pnl.el,
                'uel': pnl.uel,
                'mv': pnl.mv
            }
            for pnl in pnls
        ]

        df = pd.DataFrame(data)

        if df.empty:
            logger.warning("No PNL data available in the database to display.")
            return render_template("pnl.html", pnl=pnl_data, graph_html="No historical data available.")
            
        # Process DataFrame
        try:
            # Process DataFrame
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
        except Exception as err:
            logger.error(f"Error processing DataFrame: {err}")
            return "Error processing PNL data.", 500

    except Exception as err:
        logger.error(f"Error querying PNL data from the database: {err}")
        return "Error querying PNL data from the database.", 500

    # Create Plotly figure
    try:
        fig = go.Figure()

        # Add traces
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df['nl'],
            mode='lines',
            name='Net Liquidation (NL)'
        ))
        
        fig.update_layout(
            title='NAV Over Time',
            yaxis_title='Value',
            legend_title='PNL Metrics',
            template='seaborn',
            width=1000,
            height=600,
            xaxis=dict(
                rangeslider=dict(visible=False),
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1d", step="day", stepmode="backward"),
                        dict(count=7, label="1w", step="day", stepmode="backward"),
                        dict(count=1, label="1m", step="month", stepmode="backward"),
                        dict(step="all")
                    ])
                ),
                type="category",
                showticklabels=False
            )
        )

        # Convert the figure to HTML
        graph_html = to_html(fig, full_html=False)
    except Exception as err:
        logger.error(f"An error occurred while creating the PNL chart: {err}")
        return "An unexpected error occurred while creating the chart.", 500

    # Render the template with the processed pnl_data and the chart
    return render_template("pnl.html", pnl=pnl_data, graph_html=Markup(graph_html))
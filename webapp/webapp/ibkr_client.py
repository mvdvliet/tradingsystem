# ibkr_client.py
import requests
import logging
import pandas as pd
from datetime import datetime
import time
from requests.exceptions import RequestException, HTTPError, ConnectionError, Timeout

# Disable warnings until you install a certificate
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger('webapp logger')

class IBKRClient:
    """
    Client for interacting with Interactive Brokers Client Portal API.
    
    This class provides methods to interact with various IBKR API endpoints
    for retrieving account information, market data, and placing orders.
    """
    
    def __init__(self, base_url, account_id=None, max_retries=3, retry_delay=2):
        """
        Initialize the IBKR API client.
        
        Args:
            base_url (str): The base URL for the IBKR API.
            account_id (str, optional): The account ID to use for requests.
            max_retries (int, optional): Maximum number of retry attempts for API calls.
            retry_delay (int, optional): Delay between retry attempts in seconds.
        """
        # Convert HTTPS to HTTP for localhost connections
        if base_url.startswith('https://') and ('localhost' in base_url or '127.0.0.1' in base_url):
            self.base_url = base_url.replace('https://', 'http://')
            logger.info(f"Converting HTTPS to HTTP for localhost: {self.base_url}")
        else:
            self.base_url = base_url
            
        self.account_id = account_id
        self.session = requests.Session()
        # Disable SSL verification for localhost connections
        self.verify_ssl = not ('localhost' in self.base_url or '127.0.0.1' in self.base_url)
        self.session.verify = self.verify_ssl
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        logger.info(f"Initialized IBKR client with base URL: {self.base_url}, SSL verification: {self.verify_ssl}")
    
    def _make_request(self, method, endpoint, **kwargs):
        """
        Make an HTTP request to the IBKR API with retry logic.
        
        Args:
            method (str): HTTP method (get, post, delete, etc.)
            endpoint (str): API endpoint to call
            **kwargs: Additional arguments to pass to the request
            
        Returns:
            dict or None: JSON response if successful, None otherwise
        """
        url = f"{self.base_url}/{endpoint}"
        
        # Ensure verify is set correctly for all requests
        if 'verify' not in kwargs:
            kwargs['verify'] = self.verify_ssl
            
        logger.debug(f"Making {method.upper()} request to {url}")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                response = getattr(self.session, method)(url, **kwargs)
                response.raise_for_status()
                return response.json()
            except ValueError as e:
                logger.error(f"Invalid JSON response on attempt {attempt}: {e}")
            except HTTPError as e:
                logger.error(f"HTTP error on attempt {attempt}: {e}")
                # Log response content for debugging
                try:
                    logger.error(f"Response content: {response.text}")
                except:
                    pass
            except ConnectionError as e:
                logger.error(f"Connection error on attempt {attempt}: {e}")
            except Timeout as e:
                logger.error(f"Timeout error on attempt {attempt}: {e}")
            except RequestException as e:
                logger.error(f"Request exception on attempt {attempt}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt}: {e}")
            
            if attempt < self.max_retries:
                logger.info(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)
            else:
                logger.error(f"Failed after {self.max_retries} attempts")
                return None
    
    
    def get_session_status(self):
        """
        Check the status of the current session.
        
        Returns:
            dict or None: Session status if successful, None otherwise
        """
        logger.debug("Checking session status")
        return self._make_request('get', 'tickle')

    def reauthenticate(self):
        """
        Attempt to reauthenticate the session.
        
        Returns:
            dict or None: Reauthentication response if successful, None otherwise
        """
        return self._make_request('get', 'iserver/reauthenticate')
    
    def get_accounts(self):
        """
        Get list of accounts.
        
        Returns:
            list or None: List of account objects if successful, None otherwise
        """
        return self._make_request('get', 'portfolio/accounts')
    
    def get_account_summary(self, account_id=None):
        """
        Get account summary.
        
        Args:
            account_id (str, optional): Account ID to get summary for.
                If not provided, uses the account ID from initialization.
                
        Returns:
            dict or None: Account summary if successful, None otherwise
        """
        account_id = account_id or self.account_id
        if not account_id:
            logger.error("No account ID provided")
            return None
            
        return self._make_request('get', f'portfolio/{account_id}/summary')
    
    def get_price_history(self, symbol, conid, period='3m', bar='1h'):
        """
        Retrieves historical price data for a given contract identifier (conid).
        
        Parameters:
        - symbol (str): Trading symbol for logging purposes
        - conid (int): Contract identifier of the symbol
        - period (str): Period over which to retrieve historical data
          Available time periods: {1-30}min, {1-8}h, {1-1000}d, {1-792}w, {1-182}m, {1-15}y
        - bar (str): Granularity of the data bars
          Possible values: 1min, 2min, 3min, 5min, 10min, 15min, 30min, 1h, 2h, 3h, 4h, 8h, 1d, 1w, 1m

        Returns:
        - pandas.DataFrame or None: DataFrame containing historical price data or None if error
        """
        endpoint = f"iserver/marketdata/history?conid={conid}&period={period}&bar={bar}"
        price_history = self._make_request('get', endpoint)
        
        if not price_history:
            logger.error(f"Failed to retrieve price history for {symbol} (conid {conid})")
            return None
            
        data_list = price_history.get('data', [])
        if not data_list:
            logger.info(f"No price data available for {symbol}")
            return None

        stock_data = pd.DataFrame(data_list)

        if not stock_data.empty:
            # Rename columns to standard OHLCV format
            stock_data.rename(columns={
                'o': 'Open', 
                'h': 'High', 
                'l': 'Low', 
                'c': 'Close', 
                'v': 'Volume', 
                't': 'Date'
            }, inplace=True)

            # Convert 'Date' from timestamp to datetime object
            stock_data['Date'] = pd.to_datetime(stock_data['Date'], unit='ms')

            # Set 'Date' as the index
            stock_data.set_index('Date', inplace=True)

            # Ensure the DataFrame only contains necessary columns
            stock_data = stock_data[['Open', 'High', 'Low', 'Close', 'Volume']]
            logger.info(f"Stock data prepared for {symbol}")
            return stock_data
        else:
            logger.info(f"Stock data is empty for {symbol}")
            return None
    
    def get_market_data(self, contract_id):
        """Get market data for a specific contract with enhanced retry logic"""
        try:
            logger.info(f"Getting market data for contract {contract_id}")
            
            # Step 1: Perform the pre-flight request to ensure authentication
            accounts_response = self._make_request('get', 'iserver/accounts')
            if not accounts_response:
                logger.error("Failed to perform pre-flight request to iserver/accounts")
                return None
            
            logger.debug(f"Pre-flight request successful: {accounts_response}")
            
            # Step 2: Make the actual market data request with enhanced retry logic
            for attempt in range(1, self.max_retries + 1):
                try:
                    # Make the API call to get market data
                    endpoint = f"iserver/marketdata/snapshot?conids={contract_id}&fields=31,70,71,73,74,75,76,78,79,80,82,83,84,86,87,7289,7295,7296"
                    response = self._make_request('get', endpoint)
                    
                    if response and isinstance(response, list) and len(response) > 0:
                        # Get the first item in the response
                        market_data = response[0]
                        
                        # Ensure all expected fields exist (with default values if missing)
                        expected_fields = ['31', '70', '71', '73', '74', '75', '76', '78', '79', '80', 
                                        '82', '83', '84', '86', '87', '7289', '7295', '7296']
                        
                        for field in expected_fields:
                            if field not in market_data:
                                market_data[field] = 'N/A'
                        
                        # Check if all values are N/A, which indicates we should retry
                        all_na = True
                        critical_fields = ['31', '73', '74', '75', '76', '78']  # Most important fields
                        
                        for field in critical_fields:
                            if market_data.get(field) != 'N/A':
                                all_na = False
                                break
                        
                        if all_na:
                            logger.warning(f"All critical market data values are N/A for {contract_id} on attempt {attempt}. Retrying...")
                            
                            if attempt < self.max_retries:
                                # Wait a bit longer for N/A retries
                                retry_delay = self.retry_delay * 2
                                logger.info(f"Waiting {retry_delay} seconds before retrying...")
                                time.sleep(retry_delay)
                                continue
                            else:
                                logger.warning(f"All market data values are N/A for {contract_id}. This may indicate the stock is not actively traded.")
                        
                        # Log the data we received
                        logger.info(f"Market data keys: {market_data.keys()}")
                        logger.info(f"Market data content: {market_data}")
                        return market_data
                    else:
                        logger.error(f"Invalid market data response for contract {contract_id} on attempt {attempt}")
                        
                        if attempt < self.max_retries:
                            logger.info(f"Retrying in {self.retry_delay} seconds...")
                            time.sleep(self.retry_delay)
                        else:
                            logger.error(f"Failed to get market data after {self.max_retries} attempts")
                            return None
                except Exception as e:
                    logger.error(f"Error getting market data for contract {contract_id} on attempt {attempt}: {e}")
                    
                    if attempt < self.max_retries:
                        logger.info(f"Retrying in {self.retry_delay} seconds...")
                        time.sleep(self.retry_delay)
                    else:
                        logger.error(f"Failed to get market data after {self.max_retries} attempts")
                        return None
            
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_market_data for contract {contract_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            return None
    
    def get_contract_details(self, conid):
        """
        Get contract details for a specific contract.
        
        Args:
            conid (int): Contract identifier
            
        Returns:
            dict or None: Contract details if successful, None otherwise
        """
        return self._make_request('get', f'iserver/contract/{conid}/info')
    
    def place_order(self, order_details):
        """
        Place an order through the broker's API.
        
        Args:
            order_details (dict): Order details including conid, orderType, quantity, side, etc.
            
        Returns:
            str or None: Order ID if successful, None otherwise
        """
        # Get account ID if not already set
        if not self.account_id:
            accounts = self.get_accounts()
            if not accounts:
                logger.error("Failed to retrieve accounts")
                return None
                
            self.account_id = accounts[0]["id"]
        
        # Place the order
        order_payload = {"orders": [order_details]}
        response = self._make_request('post', f'iserver/account/{self.account_id}/orders', json=order_payload)
        
        if not response:
            return None
            
        if isinstance(response, list) and response:
            order_info = response[0]
            if 'id' in order_info:
                order_id = order_info['id']
                logger.info(f"Order placed successfully with ID: {order_id}")
                return order_id
            else:
                logger.error(f"Order response does not contain 'id': {order_info}")
                return None
        else:
            logger.error(f"Unexpected order response: {response}")
            return None
    
    def confirm_order(self, order_id):
        """
        Confirm an order after it's been placed.
        
        Args:
            order_id (str): ID of the order to confirm
            
        Returns:
            dict or None: Confirmation response if successful, None otherwise
        """
        return self._make_request('post', f'iserver/reply/{order_id}', json={"confirmed": True})
    
    def cancel_order(self, order_id):
        """
        Cancel an existing order.
        
        Args:
            order_id (str): ID of the order to cancel
            
        Returns:
            dict or None: Cancellation response if successful, None otherwise
        """
        if not self.account_id:
            accounts = self.get_accounts()
            if not accounts:
                logger.error("Failed to retrieve accounts")
                return None
                
            self.account_id = accounts[0]["id"]
            
        return self._make_request('delete', f'iserver/account/{self.account_id}/order/{order_id}')
    
    def get_orders(self):
        """
        Get list of current orders.
        
        Returns:
            list or None: List of orders if successful, None otherwise
        """
        try:
            logger.info("Getting orders from IBKR API")
            
            # Step 1: Perform the pre-flight request to ensure authentication
            accounts_response = self._make_request('get', 'iserver/accounts')
            if not accounts_response:
                logger.error("Failed to perform pre-flight request to iserver/accounts")
                return None
            
            logger.debug(f"Pre-flight request successful: {accounts_response}")
            
            # Step 2: Make the actual orders request
            response = self._make_request('get', 'iserver/account/orders')
            
            if not response:
                logger.error("Failed to get orders")
                return None
            
            # Log the structure of the response for debugging
            logger.debug(f"Orders response keys: {list(response.keys()) if isinstance(response, dict) else 'Not a dict'}")
            
            # Handle different response formats
            if isinstance(response, dict):
                if 'orders' in response:
                    orders = response['orders']
                    logger.info(f"Found {len(orders)} orders in 'orders' key")
                    return orders
                elif 'live' in response:
                    orders = response['live']
                    logger.info(f"Found {len(orders)} orders in 'live' key")
                    return orders
                else:
                    # Try to find any list in the response that might contain orders
                    for key, value in response.items():
                        if isinstance(value, list) and len(value) > 0:
                            logger.info(f"Found potential orders in '{key}' key")
                            return value
                    
                    logger.warning("No orders found in response")
                    return []
            elif isinstance(response, list):
                # The response itself is a list of orders
                logger.info(f"Found {len(response)} orders in response list")
                return response
            else:
                logger.error(f"Unexpected response type: {type(response)}")
                return None
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def get_trades(self, days=30):
        """
        Get list of trades for the specified number of days.
        
        Args:
            days (int, optional): Number of days to retrieve trades for
            
        Returns:
            list or None: List of trades if successful, None otherwise
        """
        return self._make_request('get', f'iserver/account/trades?days={days}')
    
    def get_positions(self):
        """
        Get current positions in the portfolio.
        
        Returns:
            list or None: List of positions if successful, None otherwise
        """
        if not self.account_id:
            accounts = self.get_accounts()
            if not accounts:
                logger.error("Failed to retrieve accounts")
                return None
                
            self.account_id = accounts[0]["id"]
            
        return self._make_request('get', f'portfolio/{self.account_id}/positions/0')
    
    def get_pnl(self):
        """Get PNL data from the IBKR API"""
        try:
            logger.info("Getting PNL data from IBKR API")
            
            # Step 1: Perform the pre-flight request to ensure authentication
            accounts_response = self._make_request('get', 'iserver/accounts')
            if not accounts_response:
                logger.error("Failed to perform pre-flight request to iserver/accounts")
                return None
            
            logger.debug(f"Pre-flight request successful: {accounts_response}")
            
            # Step 2: Make the actual PNL request to the correct endpoint
            for attempt in range(1, self.max_retries + 1):
                try:
                    # Use the correct endpoint for PNL data
                    pnl_data = self._make_request('get', 'iserver/account/pnl/partitioned')
                    
                    if pnl_data:
                        logger.info("PNL data retrieved successfully")
                        logger.debug(f"PNL data content: {pnl_data}")
                        return pnl_data
                    else:
                        logger.error(f"Failed to get PNL data on attempt {attempt}")
                        
                        if attempt < self.max_retries:
                            logger.info(f"Retrying in {self.retry_delay} seconds...")
                            time.sleep(self.retry_delay)
                        else:
                            logger.error(f"Failed to get PNL data after {self.max_retries} attempts")
                            return None
                except Exception as e:
                    logger.error(f"Error getting PNL data on attempt {attempt}: {e}")
                    
                    if attempt < self.max_retries:
                        logger.info(f"Retrying in {self.retry_delay} seconds...")
                        time.sleep(self.retry_delay)
                    else:
                        logger.error(f"Failed to get PNL data after {self.max_retries} attempts")
                        return None
            
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_pnl: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def search_symbols(self, symbol):
        """
        Search for symbols/contracts.
        
        Args:
            symbol (str): Symbol to search for
            
        Returns:
            list or None: Search results if successful, None otherwise
        """
        return self._make_request('get', f'iserver/secdef/search?symbol={symbol}&name=true')
    
    def get_scanner_parameters(self):
        """
        Get available scanner parameters.
        
        Returns:
            dict or None: Scanner parameters if successful, None otherwise
        """
        return self._make_request('get', 'iserver/scanner/params')
    
    def run_scanner(self, scanner_params):
        """
        Run a market scanner with the specified parameters.
        
        Args:
            scanner_params (dict): Scanner parameters
            
        Returns:
            list or None: Scanner results if successful, None otherwise
        """
        return self._make_request('post', 'iserver/scanner/run', json=scanner_params)
    
    def extract_pnl_metrics(self, pnl_data):
        """
        Extract PNL metrics from the raw PNL data.
        
        Args:
            pnl_data (dict): Raw PNL data from the API
            
        Returns:
            dict or None: Extracted PNL metrics if successful, None otherwise
        """
        if not pnl_data:
            logger.error("Invalid PNL data: empty or None")
            return None
            
        if not isinstance(pnl_data, dict):
            logger.error(f"Invalid PNL data type: expected dict, got {type(pnl_data)}")
            return None
            
        try:
            # Log the structure of the PNL data for debugging
            logger.debug(f"PNL data keys: {list(pnl_data.keys())}")
            
            # Initialize metrics with default values
            metrics = {
                'dpl': 0.0,  # Daily P&L
                'nl': 0.0,   # Net Liquidation
                'upl': 0.0,  # Unrealized P&L
                'el': 0.0,   # Equity
                'uel': 0.0,  # Unrealized Equity
                'mv': 0.0    # Market Value
            }
            
            # Try to extract metrics using different known structures
            if 'upnl' in pnl_data and isinstance(pnl_data['upnl'], dict):
                # Structure 1: Data is in upnl -> first key -> metrics
                upnl_data = pnl_data['upnl']
                if upnl_data:
                    # Get the first key (usually an account ID)
                    first_key = next(iter(upnl_data), None)
                    if first_key and isinstance(upnl_data[first_key], dict):
                        logger.debug(f"Found PNL data in upnl[{first_key}]")
                        self._extract_metrics_from_dict(upnl_data[first_key], metrics)
                        return metrics
            
            if 'totalPerformance' in pnl_data and isinstance(pnl_data['totalPerformance'], dict):
                # Structure 2: Data is directly in totalPerformance
                logger.debug("Found PNL data in totalPerformance")
                self._extract_metrics_from_dict(pnl_data['totalPerformance'], metrics)
                return metrics
            
            # Structure 3: Data might be in account summary format
            if any(key in pnl_data for key in ['availableFunds', 'netLiquidation', 'equityWithLoanValue']):
                logger.debug("Found PNL data in account summary format")
                # Map account summary fields to our metrics
                mapping = {
                    'netLiquidation': 'nl',
                    'unrealizedPnL': 'upl',
                    'dailyPnL': 'dpl',
                    'equityWithLoanValue': 'el',
                    'marketValue': 'mv'
                }
                
                for api_field, metric_field in mapping.items():
                    if api_field in pnl_data:
                        metrics[metric_field] = self._safe_float_convert(pnl_data[api_field])
                
                # Calculate UEL if not directly available
                if 'uel' not in pnl_data and metrics['el'] > 0:
                    metrics['uel'] = metrics['el'] - metrics['nl']
                    
                return metrics
            
            # Structure 4: Try to find metrics at the top level
            found_any = False
            for field in ['dpl', 'nl', 'upl', 'el', 'uel', 'mv']:
                if field in pnl_data:
                    metrics[field] = self._safe_float_convert(pnl_data[field])
                    found_any = True
                    
            if found_any:
                logger.debug("Found PNL metrics at top level")
                return metrics
            
            # Structure 5: Search recursively for any dict that might contain our metrics
            for key, value in pnl_data.items():
                if isinstance(value, dict):
                    # Check if this dict has any of our expected fields
                    if any(field in value for field in ['dpl', 'nl', 'upl', 'mv']):
                        logger.debug(f"Found PNL data in nested key: {key}")
                        self._extract_metrics_from_dict(value, metrics)
                        return metrics
            
            # If we get here, we couldn't find the PNL data in any expected location
            logger.error(f"Failed to extract PNL metrics. Available keys: {list(pnl_data.keys())}")
            logger.debug(f"PNL data content: {pnl_data}")
            return None
        except Exception as e:
            logger.error(f"Error extracting PNL metrics: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    def _extract_metrics_from_dict(self, source_dict, metrics_dict):
        """
        Extract metrics from a source dictionary into the metrics dictionary.
        
        Args:
            source_dict (dict): Source dictionary containing PNL data
            metrics_dict (dict): Target metrics dictionary to update
        """
        for field in metrics_dict.keys():
            if field in source_dict:
                metrics_dict[field] = self._safe_float_convert(source_dict[field])
                
    def _safe_float_convert(self, value):
        """
        Safely convert a value to float, handling various formats.
        
        Args:
            value: The value to convert to float
            
        Returns:
            float: The converted value, or 0.0 if conversion fails
        """
        if value is None:
            return 0.0
            
        if isinstance(value, (int, float)):
            return float(value)
            
        if isinstance(value, str):
            # Remove commas and other non-numeric characters except decimal point and minus
            try:
                # Handle currency format (e.g., "$1,234.56")
                cleaned = value.replace(',', '').replace('$', '')
                return float(cleaned)
            except ValueError:
                logger.warning(f"Could not convert string to float: {value}")
                return 0.0
                
        logger.warning(f"Unexpected value type for float conversion: {type(value)}")
        return 0.0
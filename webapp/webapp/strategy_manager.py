# strategy_manager.py
import logging
import requests
import numpy as np
from datetime import datetime
from models import db, Strategy, TradingUniverse

logger = logging.getLogger('webapp logger')

class StrategyManager:
    """
    Manages trading strategies, including signal generation, order placement,
    and strategy lifecycle management.
    """
    
    def __init__(self, ibkr_client, email_sender=None):
        """
        Initialize the strategy manager.
        
        Args:
            ibkr_client: The IBKR client instance for API interactions
            email_sender: Optional email sender for notifications
        """
        self.ibkr_client = ibkr_client
        self.email_sender = email_sender
        self.active_strategies = {}
        logger.info("StrategyManager initialized with email notifications enabled." if email_sender else "StrategyManager initialized without email notifications.")
    
    def check_signals(self):
        """
        Scan trading universe for signals and execute appropriate actions.
        """
        universe = TradingUniverse.query.filter_by(is_active=True).all()
        
        for symbol in universe:
            # Calculate signals for all active symbols (both trading and simulation)
            signal = self.calculate_signals(symbol)
            
            # Only create/close strategies for symbols in 'trading' mode
            if signal and symbol.trading_mode == 'trading':
                if signal == 'BUY':
                    self.create_strategy(symbol)
                elif signal == 'SELL':
                    self.close_strategy(symbol)
            elif signal and symbol.trading_mode == 'simulation':
                # Log that we're skipping order execution for simulation-only symbols
                logger.info(f"Simulation mode: Detected {signal} signal for {symbol.symbol} but not executing orders")
    
    def calculate_signals(self, symbol):
        """
        Calculate buy/sell signals based on moving average crossover strategy.
        
        Args:
            symbol: The trading symbol object containing symbol info
            
        Returns:
            str or None: 'BUY', 'SELL', or None if no signal
        """
        # Get historical data
        price_history = self.ibkr_client.get_price_history(symbol.symbol, symbol.conid)
        
        if price_history is None or price_history.empty:
            logger.info(f"No price history for {symbol.symbol} (conid {symbol.conid}).")
            return None
        
        # Calculate indicators (e.g., moving averages)
        df = price_history.copy()
        df['SMA_short'] = df['Close'].rolling(window=5).mean()
        df['SMA_long'] = df['Close'].rolling(window=20).mean()
        
        # Ensure that we have enough data points
        if len(df) < 20:
            logger.info(f"Not enough data to calculate moving averages for {symbol.symbol} (conid {symbol.conid}).")
            return None
        
        # Calculate the difference between SMA_short and SMA_long to detect crossovers
        df['Signal'] = df['SMA_short'] - df['SMA_long']

        # Get the previous and current signal values
        signal_prev = df['Signal'].iloc[-2]
        signal_curr = df['Signal'].iloc[-1]
        
        # Get current price and MA values for notification
        current_price = df['Close'].iloc[-1]
        short_ma = df['SMA_short'].iloc[-1]
        long_ma = df['SMA_long'].iloc[-1]

        # Generate signals based on crossover
        signal_type = None
        if signal_prev < 0 and signal_curr > 0:
            # SMA_short crossed above SMA_long: BUY signal
            logger.info(f"BUY signal for {symbol.symbol} (conid {symbol.conid}).")
            signal_type = 'BUY'
        elif signal_prev > 0 and signal_curr < 0:
            # SMA_short crossed below SMA_long: SELL signal
            logger.info(f"SELL signal for {symbol.symbol} (conid {symbol.conid}).")
            signal_type = 'SELL'
        else:
            # No crossover
            logger.info(f"No signal for {symbol.symbol} (conid {symbol.conid}) at this time.")
            return None
        
        # Calculate signal strength as percentage change in the signal
        signal_strength = abs((signal_curr / signal_prev - 1) * 100) if signal_prev != 0 else 0
        
        # Prepare signal data for notification and database
        signal_data = {
            'signal_type': signal_type,
            'signal_strength': signal_strength,
            'detection_time': datetime.utcnow(),
            'current_price': current_price,
            'short_ma': short_ma,
            'long_ma': long_ma,
            'ma_diff': signal_curr,
            'prev_ma_diff': signal_prev
        }
        
        # Save signal to database
        try:
            from models import db, Signal
            
            # Create new signal record
            signal_record = Signal(
                symbol=symbol.symbol,
                conid=symbol.conid,
                signal_type=signal_type,
                signal_strength=signal_strength,
                detection_time=signal_data['detection_time'],
                current_price=current_price,
                short_ma=short_ma,
                long_ma=long_ma,
                ma_diff=signal_curr,
                prev_ma_diff=signal_prev,
                acted_upon=False  # Will be updated when strategy is created/closed
            )
            
            db.session.add(signal_record)
            db.session.commit()
            logger.info(f"Saved {signal_type} signal for {symbol.symbol} to database (ID: {signal_record.id})")
        except Exception as e:
            logger.error(f"Error saving signal to database: {e}")
            # Continue with email notification even if database save fails
        
        # If email sender is available, send a notification
        if self.email_sender:
            # Prepare symbol data for notification
            symbol_data = {
                'symbol': symbol.symbol,
                'conid': symbol.conid
            }
            
            # Format the detection time for email
            signal_data_email = signal_data.copy()
            signal_data_email['detection_time'] = signal_data['detection_time'].strftime('%Y-%m-%d %H:%M:%S')
            signal_data_email['current_price'] = f"{current_price:.2f}"
            signal_data_email['short_ma'] = f"{short_ma:.2f}"
            signal_data_email['long_ma'] = f"{long_ma:.2f}"
            signal_data_email['ma_diff'] = f"{signal_curr:.4f}"
            signal_data_email['prev_ma_diff'] = f"{signal_prev:.4f}"
            
            # Send signal notification
            self.email_sender.send_signal_notification(symbol_data, signal_data_email)
        
        return signal_type
    
    def calculate_position_size(self, symbol, trade_percentage=0.50):
        """
        Calculate the position size for a given symbol based on available cash and the last close price.
        
        Args:
            symbol: The trading symbol object containing symbol info
            trade_percentage: The percentage of available cash to use for the trade
            
        Returns:
            int: The number of shares to trade
        """
        # Get account summary
        account_summary = self.ibkr_client.get_account_summary()
        
        if not account_summary:
            logger.error("Failed to retrieve account summary")
            return 0
        
        # Extract available cash from the summary
        available_cash = None
        if isinstance(account_summary, dict):
            # Check if 'availabletotrade' exists and has the correct currency
            if 'availabletotrade' in account_summary:
                item = account_summary['availabletotrade']
                if isinstance(item, dict) and item.get('currency') == 'USD':
                    available_cash = float(item.get('amount'))
        else:
            # Assuming account_summary is a list of dictionaries
            for item in account_summary:
                if isinstance(item, dict) and item.get('tag') == 'availabletotrade' and item.get('currency') == 'USD':
                    available_cash = float(item.get('amount'))
                    break

        if available_cash is None:
            logger.error("AvailableFunds not found in account summary.")
            return 0  # Cannot determine position size without available cash

        # Determine amount to trade based on the specified trade percentage
        amount_to_trade = available_cash * trade_percentage
        logger.info(f"Available cash: ${available_cash:.2f}, Amount to trade: ${amount_to_trade:.2f}")

        # Get the last close price of the symbol
        price_history = self.ibkr_client.get_price_history(symbol.symbol, symbol.conid)
        if price_history is None or price_history.empty:
            logger.error(f"No price history available for {symbol.symbol} (conid {symbol.conid}).")
            return 0

        last_close_price = price_history['Close'].iloc[-1]
        logger.info(f"Last close price for {symbol.symbol}: ${last_close_price:.2f}")

        # Calculate the quantity to trade
        if last_close_price > 0:
            quantity = int(amount_to_trade / last_close_price)
            logger.info(f"Calculated position size for {symbol.symbol}: {quantity} shares")
        else:
            logger.error(f"Invalid last close price for {symbol.symbol} (conid {symbol.conid}).")
            return 0

        # Ensure that quantity is at least 1
        if quantity < 1:
            logger.warning(f"Calculated quantity is less than 1 for {symbol.symbol}.")
            return 0

        return quantity
    
    def create_strategy(self, symbol):
        """
        Create new strategy when buy signal is detected.
        
        Args:
            symbol: The trading symbol object containing symbol info
        """
        # Check if strategy already exists
        existing = Strategy.query.filter_by(
            symbol=symbol.symbol, 
            status='ACTIVE'
        ).first()
        
        if existing:
            logger.info(f"Strategy for {symbol.symbol} already exists and is active.")
            return

        # Calculate position size
        quantity = self.calculate_position_size(symbol)
        if quantity <= 0:
            logger.warning(f"Calculated position size for {symbol.symbol} is zero. Skipping order placement.")
            return

        # Create order
        order_details = {
            "conid": symbol.conid,
            "orderType": "MKT",
            "quantity": quantity,
            "side": "BUY"
        }
        
        # Place order through IBKR API
        order_id = self.ibkr_client.place_order(order_details)
        
        if order_id:
            # Create strategy record
            strategy = Strategy(
                name="MA_Crossover",
                symbol=symbol.symbol,
                conid=symbol.conid,
                status="ACTIVE",
                entry_time=datetime.utcnow(),
                position_size=quantity
            )
            db.session.add(strategy)
            
            # Mark the most recent BUY signal for this symbol as acted upon
            try:
                from models import Signal
                recent_signal = Signal.query.filter_by(
                    symbol=symbol.symbol,
                    signal_type='BUY'
                ).order_by(Signal.detection_time.desc()).first()
                
                if recent_signal:
                    recent_signal.acted_upon = True
                    logger.info(f"Marked signal ID {recent_signal.id} as acted upon")
            except Exception as e:
                logger.error(f"Error updating signal acted_upon status: {e}")
            
            db.session.commit()
            logger.info(f"Strategy for {symbol.symbol} created successfully.")

            # Send email notification if email sender is available
            if self.email_sender:
                subject = f"New Strategy Opened for {symbol.symbol}"
                html_content = f"""
                <html>
                    <body>
                        <p>Hello,</p>
                        <p>A new strategy has been opened for {symbol.symbol}.</p>
                        <p><strong>Details:</strong></p>
                        <ul>
                            <li>Symbol: {symbol.symbol}</li>
                            <li>ConID: {symbol.conid}</li>
                            <li>Quantity: {quantity}</li>
                            <li>Strategy: {strategy.name}</li>
                            <li>Entry Time: {strategy.entry_time}</li>
                        </ul>
                        <p>Best regards,<br>Your Trading Bot</p>
                    </body>
                </html>
                """
                receiver_email = 'marcel@vdvliet.com'  # Should be configurable
                self.email_sender.send_notification(subject, html_content, receiver_email)
        else:
            logger.error(f"Failed to place order for {symbol.symbol}.")
    
    def close_strategy(self, symbol):
        """
        Close strategy when sell signal is detected.
        
        Args:
            symbol: The trading symbol object containing symbol info
        """
        # Retrieve the active strategy
        strategy = Strategy.query.filter_by(
            symbol=symbol.symbol,
            status='ACTIVE'
        ).first()
        
        if not strategy:
            logger.info(f"No active strategy found for {symbol.symbol}.")
            return

        # Get position size from the strategy
        quantity = strategy.position_size
        if quantity <= 0:
            logger.warning(f"Position size for {symbol.symbol} is zero or invalid. Skipping order placement.")
            return
            
        # Create sell order
        order_details = {
            "conid": symbol.conid,
            "orderType": "MKT", 
            "quantity": quantity,
            "side": "SELL"
        }
        
        # Place order through IBKR API
        order_id = self.ibkr_client.place_order(order_details)
        
        if order_id:
            # Update strategy record
            strategy.status = "CLOSED"
            strategy.exit_time = datetime.utcnow()
            
            # Mark the most recent SELL signal for this symbol as acted upon
            try:
                from models import Signal
                recent_signal = Signal.query.filter_by(
                    symbol=symbol.symbol,
                    signal_type='SELL'
                ).order_by(Signal.detection_time.desc()).first()
                
                if recent_signal:
                    recent_signal.acted_upon = True
                    logger.info(f"Marked signal ID {recent_signal.id} as acted upon")
            except Exception as e:
                logger.error(f"Error updating signal acted_upon status: {e}")
            
            db.session.commit()
            logger.info(f"Strategy for {symbol.symbol} closed successfully.")

            # Send email notification if email sender is available
            if self.email_sender:
                subject = f"Strategy Closed for {symbol.symbol}"
                html_content = f"""
                <html>
                    <body>
                        <p>Hello,</p>
                        <p>A strategy has been closed for {symbol.symbol}.</p>
                        <p><strong>Details:</strong></p>
                        <ul>
                            <li>Symbol: {symbol.symbol}</li>
                            <li>ConID: {symbol.conid}</li>
                            <li>Quantity: {quantity}</li>
                            <li>Close Time: {strategy.exit_time}</li>
                        </ul>
                        <p>Best regards,<br>Your Trading Bot</p>
                    </body>
                </html>
                """
                receiver_email = 'marcel@vdvliet.com'  # Should be configurable
                self.email_sender.send_notification(subject, html_content, receiver_email)
        else:
            logger.error(f"Failed to place sell order for {symbol.symbol}.")
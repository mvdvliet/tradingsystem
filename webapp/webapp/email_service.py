# email_service.py
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger('webapp logger')

class EmailService:
    """
    Service for sending email notifications.
    """
    
    def __init__(self, sender_email, sender_password, smtp_server='smtp.gmail.com', smtp_port=465):
        """
        Initialize the email service.
        
        Args:
            sender_email: The email address to send from
            sender_password: The password or app password for the sender email
            smtp_server: The SMTP server to use
            smtp_port: The SMTP port to use
        """
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
    
    def send_email_notification(self, subject, html_content, receiver_email=None):
        """
        Sends an email with the given subject and HTML content to the specified receiver email.
        
        Args:
            subject: The email subject
            html_content: The HTML content of the email
            receiver_email: The recipient's email address (optional)
            
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        from config import get_config
        config = get_config()
        
        # Use instance variables with fallback to config
        email_sender = self.sender_email or config.EMAIL_SENDER
        email_app_password = self.sender_password or config.EMAIL_APP_PASSWORD
        email_receiver = receiver_email or config.EMAIL_RECEIVER
        
        # Create the message container
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = email_sender
        msg['To'] = email_receiver

        # Attach the HTML body to the email
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send the email via SMTP server
        context = ssl.create_default_context()
        
        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as smtp:
                smtp.login(email_sender, email_app_password)
                smtp.send_message(msg)
            logger.info(f'Email "{subject}" sent successfully to {email_receiver}!')
            return True
        except Exception as e:
            logger.error(f"Failed to send email '{subject}' to {email_receiver}: {e}")
            return False

    def send_notification(self, subject, html_content, receiver_email):
        """
        Send an email notification.
        
        Args:
            subject: The email subject
            html_content: The HTML content of the email
            receiver_email: The recipient's email address
            
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        # Create the message container
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.sender_email
        msg['To'] = receiver_email

        # Attach the HTML body to the email
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send the email via SMTP server
        context = ssl.create_default_context()
        
        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as smtp:
                smtp.login(self.sender_email, self.sender_password)
                smtp.send_message(msg)
            logger.info(f'Email "{subject}" sent successfully to {receiver_email}!')
            return True
        except Exception as e:
            logger.error(f"Failed to send email '{subject}' to {receiver_email}: {e}")
            return False
    
    def send_pnl_notification(self, pnl_data, account_summary=None):
        """
        Send a PNL notification email.
        
        Args:
            pnl_data: Dictionary containing PNL data
            account_summary: Optional dictionary containing account summary data
            
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        subject = "Your Latest PNL Data"
        
        # Format the email content
        html_content = f'''
        <html>
        <body>
            <p>Hello,</p>

            <p>Here is your latest PNL data:</p>

            <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Timestamp</td>
                <td>{pnl_data.get('timestamp', 'N/A')}</td>
            </tr>
            <tr>
                <td>Daily Profit and Loss value (DPL)</td>
                <td>{pnl_data.get('dpl', 0):,.2f}</td>
            </tr>
            <tr>
                <td>Unrealized Profit and Loss for the day (UPL)</td>
                <td>{pnl_data.get('upl', 0):,.2f}</td>
            </tr>
            <tr>
                <td>Excess Liquidity (UEL)</td>
                <td>{pnl_data.get('uel', 0):,.2f}</td>
            </tr>
            <tr>
                <td>Market Value (MV)</td>
                <td>{pnl_data.get('mv', 0):,.2f}</td>
            </tr>
            <tr>
                <td>Net Liquidity (NL)</td>
                <td>{pnl_data.get('nl', 0):,.2f}</td>
            </tr>
            </table>
        '''
                
        html_content += '''
            <p>Best regards,<br>
            Your Automated PNL Reporter</p>
        </body>
        </html>
        '''
        
        return self.send_notification(subject, html_content, 'marcel@vdvliet.com')
    
    def send_auth_alert(self):
        """
        Send an authentication alert email.
        
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        subject = "Authentication Alert - Session Invalid"
        html_content = """
        <html>
            <body>
                <h2>Authentication Alert</h2>
                <p>Your session has become invalid or unauthenticated.</p>
                <p>Please log in again at: <a href="https://localhost:5055">Login Page</a></p>
            </body>
        </html>
        """
        return self.send_notification(subject, html_content, 'marcel@vdvliet.com')
    
    def send_strategy_notification(self, strategy_type, symbol_data, strategy_data):
        """
        Send a strategy notification email.
        
        Args:
            strategy_type: 'open' or 'close'
            symbol_data: Dictionary containing symbol data
            strategy_data: Dictionary containing strategy data
            
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        if strategy_type == 'open':
            subject = f"New Strategy Opened for {symbol_data.get('symbol', 'Unknown')}"
            html_content = f"""
            <html>
                <body>
                    <p>Hello,</p>
                    <p>A new strategy has been opened for {symbol_data.get('symbol', 'Unknown')}.</p>
                    <p><strong>Details:</strong></p>
                    <ul>
                        <li>Symbol: {symbol_data.get('symbol', 'Unknown')}</li>
                        <li>ConID: {symbol_data.get('conid', 'Unknown')}</li>
                        <li>Quantity: {strategy_data.get('position_size', 'Unknown')}</li>
                        <li>Strategy: {strategy_data.get('name', 'Unknown')}</li>
                        <li>Entry Time: {strategy_data.get('entry_time', 'Unknown')}</li>
                    </ul>
                    <p>Best regards,<br>Your Trading Bot</p>
                </body>
            </html>
            """
        else:  # close
            subject = f"Strategy Closed for {symbol_data.get('symbol', 'Unknown')}"
            html_content = f"""
            <html>
                <body>
                    <p>Hello,</p>
                    <p>A strategy has been closed for {symbol_data.get('symbol', 'Unknown')}.</p>
                    <p><strong>Details:</strong></p>
                    <ul>
                        <li>Symbol: {symbol_data.get('symbol', 'Unknown')}</li>
                        <li>ConID: {symbol_data.get('conid', 'Unknown')}</li>
                        <li>Quantity: {strategy_data.get('position_size', 'Unknown')}</li>
                        <li>Close Time: {strategy_data.get('exit_time', 'Unknown')}</li>
                    </ul>
                    <p>Best regards,<br>Your Trading Bot</p>
                </body>
            </html>
            """
        
        return self.send_notification(subject, html_content, 'marcel@vdvliet.com')

    def send_signal_notification(self, symbol_data, signal_data):
        """
        Send a signal notification email when a strategy detects a signal.
        
        Args:
            symbol_data: Dictionary containing symbol data
            signal_data: Dictionary containing signal data
            
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        signal_type = signal_data.get('signal_type', 'Unknown')
        subject = f"Trading Signal Detected: {signal_type} for {symbol_data.get('symbol', 'Unknown')}"
        
        # Format the signal strength as a percentage if it's a number
        signal_strength = signal_data.get('signal_strength', 'N/A')
        if isinstance(signal_strength, (int, float)):
            signal_strength = f"{signal_strength:.2f}%"
        
        # Create a color based on signal type
        signal_color = "#28a745" if signal_type == "BUY" else "#dc3545" if signal_type == "SELL" else "#6c757d"
        
        html_content = f"""
        <html>
            <body>
                <p>Hello,</p>
                <p>A trading signal has been detected:</p>
                
                <div style="padding: 15px; border-left: 4px solid {signal_color}; background-color: #f8f9fa; margin: 20px 0;">
                    <h3 style="color: {signal_color}; margin-top: 0;">{signal_type} Signal for {symbol_data.get('symbol', 'Unknown')}</h3>
                    
                    <p><strong>Signal Details:</strong></p>
                    <ul>
                        <li>Symbol: {symbol_data.get('symbol', 'Unknown')}</li>
                        <li>ConID: {symbol_data.get('conid', 'Unknown')}</li>
                        <li>Signal Type: {signal_type}</li>
                        <li>Signal Strength: {signal_strength}</li>
                        <li>Detection Time: {signal_data.get('detection_time', 'Unknown')}</li>
                        <li>Current Price: ${signal_data.get('current_price', 'Unknown')}</li>
                    </ul>
                    
                    <p><strong>Technical Indicators:</strong></p>
                    <ul>
                        <li>Short MA (5): ${signal_data.get('short_ma', 'Unknown')}</li>
                        <li>Long MA (20): ${signal_data.get('long_ma', 'Unknown')}</li>
                        <li>MA Difference: ${signal_data.get('ma_diff', 'Unknown')}</li>
                        <li>Previous MA Difference: ${signal_data.get('prev_ma_diff', 'Unknown')}</li>
                    </ul>
                </div>
                
                <p>This is an informational notification only. The system will automatically execute trades based on your configured strategy settings.</p>
                
                <p>Best regards,<br>Your Trading Bot</p>
            </body>
        </html>
        """
        
        return self.send_notification(subject, html_content, 'marcel@vdvliet.com')
FROM debian:bookworm-slim

# Update and upgrade packages
RUN apt-get update && apt-get upgrade -y

# Install JDK and any needed utilities
RUN apt-get install -y unzip curl procps vim net-tools wget \
                       python3 python3-pip python3.11-venv

# We will put everything in the /app directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt /app/

# Create and activate virtual environment
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Install dependencies in the virtual environment
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the application code (only once)
COPY webapp/ /app/webapp/

# Copy and make executable the start script
COPY start.sh /app/
RUN chmod +x /app/start.sh

# Expose the port so we can connect
EXPOSE 5056

# Run the application
CMD ["/app/start.sh"]
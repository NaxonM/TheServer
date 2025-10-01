# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the application's code from the host to the container
COPY . .

# Install any needed packages specified in requirements_cli.txt
# We use the same requirements file as it now contains Flask
RUN pip install --no-cache-dir -r requirements_cli.txt

# Create the directory for downloads within the container
RUN mkdir -p /downloads

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define the command to run the application with Gunicorn
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "web_api:app"]
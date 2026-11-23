FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# WORKDIR is the parent of the smart_home_agent/ package -- the one directory
# adk web must be run from (see README: run from the wrong one and every
# message 422s). Copying the whole repo in and setting WORKDIR here means the
# container can't get that wrong.
CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8000"]

#!/usr/bin/env python3
"""
Python script to upload a file to Google Drive using the Google Drive API v3.
"""

import os
import argparse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# Scopes required to upload files to Google Drive.
# 'https://www.googleapis.com/auth/drive.file' is recommended as it only grants
# access to files created/opened by this application.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def get_credentials(credentials_file="credentials.json", token_file="token.json"):
    """
    Get user credentials from token.json, credentials.json, or environment defaults.
    """
    creds = None
    
    # 1. Try to load existing tokens from token.json
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception as e:
            print(f"Warning: Could not load token file: {e}")

    # 2. If no valid credentials, try the OAuth 2.0 flow using credentials.json
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            if os.path.exists(credentials_file):
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open(token_file, "w") as token:
                    token.write(creds.to_json())
            else:
                # 3. Fallback to application default credentials (e.g. Service Account in GCP)
                try:
                    print("No credentials.json found. Attempting Application Default Credentials...")
                    creds, _ = google.auth.default(scopes=SCOPES)
                except Exception as e:
                    raise FileNotFoundError(
                        f"Could not authenticate. Please place your '{credentials_file}' "
                        f"file in the current directory or set up Application Default Credentials. "
                        f"Error: {e}"
                    )
    return creds

def upload_file(file_path, folder_id=None, mime_type=None):
    """
    Uploads a file to Google Drive.
    """
    if not os.path.exists(file_path):
        print(f"Error: Local file '{file_path}' does not exist.")
        return None

    file_name = os.path.basename(file_path)
    creds = get_credentials()

    try:
        # Build the Drive service
        service = build("drive", "v3", credentials=creds)

        # Define file metadata
        file_metadata = {
            "name": file_name
        }
        if folder_id:
            file_metadata["parents"] = [folder_id]

        # Prepare the media for upload
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

        # Upload the file
        print(f"Uploading '{file_name}' to Google Drive...")
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
            .execute()
        )

        print("Upload successful!")
        print(f"File Name: {file.get('name')}")
        print(f"File ID: {file.get('id')}")
        print(f"Web View Link: {file.get('webViewLink')}")
        return file

    except HttpError as error:
        print(f"An API error occurred: {error}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Upload a file to Google Drive.")
    parser.add_argument("file_path", help="Path to the local file to upload.")
    parser.add_argument("--folder", help="Optional Google Drive folder ID to upload into.")
    parser.add_argument("--mimetype", help="Optional MIME type for the file.")
    args = parser.parse_args()

    upload_file(args.file_path, folder_id=args.folder, mime_type=args.mimetype)

if __name__ == "__main__":
    main()

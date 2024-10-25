from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import SpreadsheetNotFound, APIError
import json
from typing import Tuple, List

class SheetManager:
    def __init__(self, service_account_path: str):
        try:
            self.scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/spreadsheets'
            ]
            
            # Load and validate credentials
            with open(service_account_path) as f:
                creds_data = json.load(f)
                self.service_account_email = creds_data.get('client_email')
                
            self.creds = Credentials.from_service_account_file(
                service_account_path, scopes=self.scope
            )
            self.client = gspread.authorize(self.creds)
            
        except FileNotFoundError:
            raise Exception(f"Credentials file not found at: {service_account_path}")
        except json.JSONDecodeError:
            raise Exception("Invalid credentials file format")
        except Exception as e:
            raise Exception(f"Error initializing SheetManager: {str(e)}")

    def verify_sheet_access(self, sheet_url: str) -> Tuple[bool, str]:
        """Verify if service account has access to the sheet"""
        try:
            # Extract sheet ID from URL
            sheet_id = sheet_url.split('/d/')[1].split('/')[0]
            
            # Try to open the sheet
            sheet = self.client.open_by_key(sheet_id)
            worksheet = sheet.sheet1
            
            # Try a simple read operation to verify access
            worksheet.row_count
            
            return True, "Access verified"
            
        except SpreadsheetNotFound:
            return False, f"Sheet not found. Please share the sheet with {self.service_account_email}"
        except APIError as e:
            if 'insufficient permissions' in str(e).lower():
                return False, f"Insufficient permissions. Please give Editor access to {self.service_account_email}"
            return False, f"API Error: {str(e)}"
        except Exception as e:
            return False, f"Error accessing sheet: {str(e)}"

    def initialize_sheet(self, sheet_url: str, headers: List[str]) -> Tuple[bool, str]:
        """Initialize a new sheet with headers"""
        try:
            # First verify access
            has_access, message = self.verify_sheet_access(sheet_url)
            if not has_access:
                return False, message

            # Extract sheet ID from URL
            sheet_id = sheet_url.split('/d/')[1].split('/')[0]
            worksheet = self.client.open_by_key(sheet_id).sheet1
            
            try:
                # Clear existing content
                worksheet.clear()
                
                # Set headers as first row
                worksheet.update('A1:C1', [headers])
                
                # Format headers
                worksheet.format('A1:C1', {
                    "backgroundColor": {
                        "red": 0.9,
                        "green": 0.9,
                        "blue": 0.9
                    },
                    "textFormat": {
                        "bold": True,
                        "fontSize": 11
                    },
                    "horizontalAlignment": "CENTER"
                })
                
                # Auto-resize columns based on content
                for i, header in enumerate(headers, start=1):
                    worksheet.columns_auto_resize(i-1, i)
                
                # Freeze header row
                worksheet.freeze(rows=1)
                
                return True, "Sheet initialized successfully"
                
            except APIError as e:
                return False, f"Error initializing sheet: {str(e)}"
                
        except Exception as e:
            return False, f"Error accessing sheet: {str(e)}"

    def update_user_response(self, sheet_url: str, user_email: str, num_pings: int, decision: str) -> Tuple[bool, str]:
        """Update user response in Google Sheet"""
        try:
            # First verify access
            has_access, message = self.verify_sheet_access(sheet_url)
            if not has_access:
                return False, message

            # Extract sheet ID and access sheet
            sheet_id = sheet_url.split('/d/')[1].split('/')[0]
            worksheet = self.client.open_by_key(sheet_id).sheet1
            
            try:
                # Find user row or create new one
                try:
                    cell = worksheet.find(user_email)
                    row_num = cell.row
                except:
                    # Add new row if user not found
                    values = worksheet.get_all_values()
                    row_num = len(values) + 1
                    # Update all columns for the new row
                    worksheet.update(f'A{row_num}:C{row_num}', 
                                  [[user_email, str(num_pings), decision]])
                    return True, "User added successfully"

                # Update existing row
                worksheet.update(f'B{row_num}', str(num_pings))
                worksheet.update(f'C{row_num}', decision)
                
                return True, "Response updated successfully"
                
            except APIError as e:
                return False, f"Error updating sheet: {str(e)}"
                
        except Exception as e:
            return False, f"Error accessing sheet: {str(e)}"
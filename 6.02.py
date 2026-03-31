import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import re
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

class RequestSenderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Request Sender Project Tester")
        self.root.geometry("610x730")  # Reduced dimensions

        # Task control variables
        self.is_running = False
        self.pending_task_id = None

        # Thread pool for async HTTP requests (prevents UI lag)
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Cleanup on window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Create main container with reduced padding
        main_container = tk.Frame(root)
        main_container.pack(fill='both', expand=True, padx=8, pady=8)

        # Title - smaller font
        tk.Label(main_container, text="Project Request Sender Tester",
                font=('Arial', 14, 'bold')).pack(pady=(0, 8))

        # Global Control Panel - more compact
        control_frame = tk.Frame(main_container, bg='#E0E0E0', padx=12, pady=6)
        control_frame.pack(fill='x', pady=(0, 8))

        tk.Label(control_frame, text="Global Control:", font=('Arial', 10, 'bold'),
                bg='#E0E0E0').pack(side='left', padx=(0, 10))

        # Global Price input
        tk.Label(control_frame, text="Price:", font=('Arial', 9),
                bg='#E0E0E0').pack(side='left', padx=(0, 3))
        self.global_price_var = tk.StringVar()
        self.global_price_entry = tk.Entry(control_frame, textvariable=self.global_price_var, width=6,
                                           font=('Arial', 9))
        self.global_price_entry.pack(side='left', padx=(0, 8))

        # Global Size input
        tk.Label(control_frame, text="Size:", font=('Arial', 9),
                bg='#E0E0E0').pack(side='left', padx=(0, 3))
        self.global_size_var = tk.StringVar()
        self.global_size_entry = tk.Entry(control_frame, textvariable=self.global_size_var, width=6,
                                          font=('Arial', 9))
        self.global_size_entry.pack(side='left', padx=(0, 8))

        # Apply Global Button
        self.apply_global_button = tk.Button(control_frame, text="Apply All",
                                             command=self.apply_global_values,
                                             bg='#9C27B0', fg='white',
                                             font=('Arial', 9, 'bold'),
                                             width=8)
        self.apply_global_button.pack(side='left', padx=(0, 15))

        # Delay input
        tk.Label(control_frame, text="Delay (ms):", font=('Arial', 9),
                bg='#E0E0E0').pack(side='left', padx=(0, 3))
        self.delay_var = tk.StringVar(value="500")
        self.delay_entry = tk.Entry(control_frame, textvariable=self.delay_var, width=6,
                                    font=('Arial', 9))
        self.delay_entry.pack(side='left', padx=(0, 10))

        # Start/Stop Button
        self.start_stop_button = tk.Button(control_frame, text="▶ START",
                                          command=self.toggle_task,
                                          bg='#4CAF50', fg='white',
                                          font=('Arial', 10, 'bold'),
                                          width=8)
        self.start_stop_button.pack(side='left', padx=5)

        # Status label for global control
        self.global_status = tk.Label(control_frame, text="Ready", font=('Arial', 9),
                                      bg='#E0E0E0', fg='gray')
        self.global_status.pack(side='left', padx=8)
        
        # Create 2x2 grid container
        grid_container = tk.Frame(main_container)
        grid_container.pack(fill='both', expand=True, pady=(0, 8))
        
        # Configure grid weights for responsive layout
        grid_container.grid_rowconfigure(0, weight=1)
        grid_container.grid_rowconfigure(1, weight=1)
        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)
        
        # Create 4 sections in 2x2 grid
        self.sections = []
        section_positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        
        for i, (row, col) in enumerate(section_positions):
            section = self.create_section(grid_container, i+1)
            section.grid(row=row, column=col, sticky='nsew', padx=4, pady=4)
            self.sections.append(section)
        
        # Separator
        ttk.Separator(main_container, orient='horizontal').pack(fill='x', pady=6)
        
        # Common Log Area - reduced height
        log_frame = tk.Frame(main_container)
        log_frame.pack(fill='both', expand=True)
        
        tk.Label(log_frame, text="Common Log:", 
                font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 3))
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, width=120)
        self.log_text.pack(fill='both', expand=True)
        
        # Clear Log Button
        tk.Button(log_frame, text="Clear Log", command=self.clear_log,
                 bg='#FF9800', fg='white', font=('Arial', 9)).pack(anchor='e', pady=3)
    
    def create_section(self, parent, section_num):
        """Create a compact section for one request with color-coded side indicator"""
        # Auto-select side based on section number (odd = BACK, even = LAY)
        default_side = "BACK" if section_num % 2 == 1 else "LAY"
        
        section_frame = tk.LabelFrame(parent, text=f"Section {section_num}", 
                                     font=('Arial', 10, 'bold'), padx=8, pady=6)
        
        # Request Input Area - reduced height
        tk.Label(section_frame, text="Paste Request:", 
                font=('Arial', 8, 'bold')).pack(anchor='w', pady=(0, 3))
        
        request_text = scrolledtext.ScrolledText(section_frame, height=4, width=30)
        request_text.pack(fill='both', expand=True, padx=3, pady=3)
        
        # Load Button - smaller
        load_button = tk.Button(section_frame, text="Load Request", 
                               command=lambda sn=section_num: self.load_request(sn),
                               bg='#4CAF50', fg='white', font=('Arial', 8))
        load_button.pack(pady=3)
        
        # Parameters Frame - more compact
        params_frame = tk.Frame(section_frame)
        params_frame.pack(fill='x', padx=3, pady=6)
        
        # Price and Size in one row
        row1 = tk.Frame(params_frame)
        row1.pack(fill='x', pady=2)
        
        tk.Label(row1, text="Price:", width=6, anchor='w', font=('Arial', 8)).pack(side='left')
        price_var = tk.StringVar()
        price_entry = tk.Entry(row1, textvariable=price_var, width=12, font=('Arial', 8))
        price_entry.pack(side='left', padx=(0, 10))
        
        tk.Label(row1, text="Size:", width=5, anchor='w', font=('Arial', 8)).pack(side='left')
        size_var = tk.StringVar()
        size_entry = tk.Entry(row1, textvariable=size_var, width=12, font=('Arial', 8))
        size_entry.pack(side='left')
        
        # Side selection with colored indicator (no text labels)
        row2 = tk.Frame(params_frame)
        row2.pack(fill='x', pady=5)
        
        tk.Label(row2, text="Side:", width=6, anchor='w', font=('Arial', 8)).pack(side='left')
        
        side_var = tk.StringVar(value=default_side)
        
        # Create color indicators without text
        back_indicator = tk.Label(row2, text="  ", 
                                  bg='#2196F3', 
                                  width=6, 
                                  height=1,
                                  relief='sunken' if default_side == "BACK" else 'raised',
                                  bd=2)
        back_indicator.pack(side='left', padx=(5, 2))
        
        lay_indicator = tk.Label(row2, text="  ",
                                 bg='#F44336',
                                 width=6,
                                 height=1,
                                 relief='sunken' if default_side == "LAY" else 'raised',
                                 bd=2)
        lay_indicator.pack(side='left', padx=(2, 0))
        
        # Bind click events to change side selection
        back_indicator.bind('<Button-1>', lambda e, sv=side_var, bi=back_indicator, li=lay_indicator: 
                           self.set_side(sv, "BACK", bi, li))
        lay_indicator.bind('<Button-1>', lambda e, sv=side_var, bi=back_indicator, li=lay_indicator:
                          self.set_side(sv, "LAY", bi, li))
        
        # Store side indicators for later updates
        side_indicators = {'back': back_indicator, 'lay': lay_indicator}
        
        # UUID
        row3 = tk.Frame(params_frame)
        row3.pack(fill='x', pady=2)
        
        tk.Label(row3, text="UUID:", width=6, anchor='w', font=('Arial', 8)).pack(side='left')
        uuid_var = tk.StringVar()
        uuid_entry = tk.Entry(row3, textvariable=uuid_var, width=28, font=('Arial', 8))
        uuid_entry.pack(side='left', fill='x', expand=True)
        
        # Send Button - more compact
        send_button = tk.Button(section_frame, text=f"Send",
                               command=lambda sn=section_num: self.send_single_request_async(sn),
                               bg='#2196F3', fg='white',
                               font=('Arial', 9, 'bold'),
                               height=1)
        send_button.pack(fill='x', pady=3)
        
        # Status Label for this section
        status_label = tk.Label(section_frame, text="Ready", fg='gray', font=('Arial', 8))
        status_label.pack(pady=2)
        
        # Store section data in the frame
        section_frame.section_data = {
            'section_num': section_num,
            'request_text': request_text,
            'price_var': price_var,
            'size_var': size_var,
            'side_var': side_var,
            'side_indicators': side_indicators,
            'uuid_var': uuid_var,
            'status_label': status_label,
            'url': None,
            'headers': None,
            'json_data': None
        }
        
        return section_frame
    
    def set_side(self, side_var, side, back_indicator, lay_indicator):
        """Set the side selection and update indicator appearance"""
        side_var.set(side)
        
        if side == "BACK":
            back_indicator.config(relief='sunken')
            lay_indicator.config(relief='raised')
        else:
            back_indicator.config(relief='raised')
            lay_indicator.config(relief='sunken')
    
    def clean_json_text(self, json_text):
        """Clean and fix common JSON issues"""
        # Remove trailing commas before closing braces/brackets
        json_text = re.sub(r',\s*}', '}', json_text)
        json_text = re.sub(r',\s*]', ']', json_text)
        
        # Remove any trailing parentheses (common copy-paste issue)
        json_text = json_text.rstrip(')')
        
        # Remove any trailing characters after the closing brace
        # Find the last closing brace
        last_brace = json_text.rfind('}')
        if last_brace != -1:
            json_text = json_text[:last_brace + 1]
        
        return json_text
    
    def extract_json_from_text(self, text):
        """Extract JSON from text, handling various formats"""
        # First, try to find the JSON body by looking for the first { and matching }
        # This handles the case where request ends with extra characters like )
        
        start_idx = text.find('{')
        if start_idx == -1:
            return None
        
        # Extract from first { to end, then clean up
        json_text = text[start_idx:]
        
        # Remove trailing non-JSON characters (like the ) at the end of your requests)
        json_text = json_text.rstrip()
        while json_text and json_text[-1] not in '}]':
            json_text = json_text[:-1]
        
        # Now find the proper closing brace by counting brackets
        brace_count = 0
        bracket_count = 0
        in_string = False
        escape_next = False
        end_idx = 0
        
        for i, char in enumerate(json_text):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break
            elif char == '[':
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1
        
        if end_idx > 0:
            json_text = json_text[:end_idx]
        
        return json_text
    
    def load_request(self, section_num):
        """Parse the HTTP request and extract parameters for a section"""
        try:
            section_frame = self.sections[section_num - 1]
            section_data = section_frame.section_data
            
            # Get the request text
            request_text = section_data['request_text'].get("1.0", tk.END).strip()
            
            if not request_text:
                messagebox.showwarning("Warning", f"Please paste a request in Section {section_num} first!")
                return
            
            # Extract JSON from the text
            json_text = self.extract_json_from_text(request_text)
            
            if not json_text:
                messagebox.showerror("Error", f"Section {section_num}: No JSON data found in request!")
                self.log(f"Section {section_num}: No JSON data found")
                return
            
            # Parse JSON - FIX: Initialize json_data to None first
            json_data = None
            try:
                json_data = json.loads(json_text)
                self.log(f"Section {section_num}: JSON parsed successfully")
            except json.JSONDecodeError as e:
                # Try to fix more issues
                self.log(f"Section {section_num}: JSON parse error ({str(e)}), attempting to fix...")
                
                # Try to handle the extra parenthesis issue
                if 'Extra data' in str(e):
                    # First, try removing trailing characters that commonly cause issues
                    for trim_chars in [')', '})', '}}', '];', '])', '']:
                        try:
                            test_text = json_text
                            if trim_chars and json_text.endswith(trim_chars):
                                test_text = json_text[:-len(trim_chars)]
                            json_data = json.loads(test_text)
                            self.log(f"Section {section_num}: Fixed by removing trailing '{trim_chars}'")
                            break
                        except json.JSONDecodeError:
                            continue
                    
                    # If still not parsed, try line by line removal
                    if json_data is None:
                        lines = json_text.split('\n')
                        for i in range(len(lines), 0, -1):
                            try:
                                test_text = '\n'.join(lines[:i])
                                json_data = json.loads(test_text)
                                self.log(f"Section {section_num}: Fixed by removing trailing lines")
                                break
                            except json.JSONDecodeError:
                                continue
                
                # If still None after all attempts, raise the original error
                if json_data is None:
                    raise Exception(f"Could not parse JSON: {str(e)}")
            
            # Extract headers
            headers = {}
            lines = request_text.split('\n')
            
            for line in lines:
                line = line.strip()
                if line and ':' in line and not line.startswith('{'):
                    # Split only on the first colon
                    colon_idx = line.index(':')
                    key = line[:colon_idx].strip()
                    value = line[colon_idx + 1:].strip()
                    # Skip certain headers and lines that look like JSON
                    if key and key not in ['Content-Length', 'Accept-Encoding'] and not key.startswith('"'):
                        headers[key] = value
            
            # Extract URL
            host = headers.get('Host', 'ex.pb77.co')
            
            # Find the path from the first line if it looks like HTTP request
            path = "/customer/api/placeBets"
            if lines[0].strip():
                first_line = lines[0].strip()
                if any(method in first_line for method in ['POST', 'GET', 'PUT', 'DELETE']):
                    parts = first_line.split()
                    if len(parts) >= 2 and parts[1].startswith('/'):
                        path = parts[1]
            
            # Build URL
            url = f"https://{host}{path}"
            
            # Store parsed data
            section_data['url'] = url
            section_data['headers'] = headers
            section_data['json_data'] = json_data
            
            # Extract the first market key
            if isinstance(json_data, dict):
                market_key = list(json_data.keys())[0]
                if isinstance(json_data[market_key], list) and len(json_data[market_key]) > 0:
                    bet_data = json_data[market_key][0]
                    
                    # Update the parameter fields
                    section_data['price_var'].set(str(bet_data.get('price', '')))
                    section_data['size_var'].set(str(bet_data.get('size', '')))
                    # Keep the auto-selected side (don't override from loaded data)
                    section_data['uuid_var'].set(str(bet_data.get('betUuid', '')))
                    
                    section_data['status_label'].config(text=f"Loaded", fg='green')
                    
                    # Log to common log
                    self.log(f"Section {section_num}: Loaded - Price: {bet_data.get('price')}, Size: {bet_data.get('size')}")
                else:
                    messagebox.showerror("Error", f"Section {section_num}: Invalid bet data structure!")
                    self.log(f"Section {section_num}: Invalid bet data structure")
            else:
                messagebox.showerror("Error", f"Section {section_num}: JSON is not in expected format!")
                self.log(f"Section {section_num}: JSON is not in expected format")
                
        except Exception as e:
            messagebox.showerror("Error", f"Section {section_num}: Failed to parse request: {str(e)}")
            self.log(f"Section {section_num}: Parse error - {str(e)}")
            section_data['status_label'].config(text="Parse Error", fg='red')
    
    def send_request(self, section_num):
        """Send the HTTP request with updated parameters (UI wrapper)"""
        try:
            section_frame = self.sections[section_num - 1]
            section_data = section_frame.section_data

            # Validate fields
            price = section_data['price_var'].get()
            size = section_data['size_var'].get()
            side = section_data['side_var'].get()
            bet_uuid = section_data['uuid_var'].get()

            if not all([price, size, side, bet_uuid]):
                messagebox.showwarning("Warning", f"Section {section_num}: All fields must be filled!")
                return None

            if not section_data['json_data']:
                messagebox.showwarning("Warning", f"Section {section_num}: Please load a request first!")
                return None

            # Update JSON data with new parameters
            import copy
            json_data_copy = copy.deepcopy(section_data['json_data'])
            market_key = list(json_data_copy.keys())[0]
            bet_data = json_data_copy[market_key][0]

            # Update parameters
            try:
                bet_data['price'] = float(price)
            except ValueError:
                try:
                    bet_data['price'] = int(price)
                except:
                    bet_data['price'] = price

            bet_data['size'] = size
            bet_data['side'] = side

            # Generate new betUuid with timestamp
            timestamp = int(datetime.now().timestamp() + 2)
            selection_id = bet_data.get('selectionId', '')
            bet_data['betUuid'] = f"{market_key}_{selection_id}_0__{timestamp}_INLINE"

            # Update the UUID field with new value
            section_data['uuid_var'].set(bet_data['betUuid'])

            # Log the UUID change
            self.log(f"Section {section_num}: New UUID timestamp: {timestamp}")

            # Prepare request headers
            headers = {k: v for k, v in section_data['headers'].items()}

            # Update CSRF token if present
            if 'X-Csrf-Token' in headers:
                cookie = headers.get('Cookie', '')
                if 'CSRF-TOKEN=' in cookie:
                    csrf_token = cookie.split('CSRF-TOKEN=')[-1].split(';')[0]
                    if csrf_token:
                        headers['X-Csrf-Token'] = csrf_token

            section_data['status_label'].config(text="Sending...", fg='blue')

            # Log sending
            self.log(f"Section {section_num}: Sending {side} - Price={price}, Size={size}")

            # Return data needed for async send
            return {
                'section_num': section_num,
                'url': section_data['url'],
                'json_data': json_data_copy,
                'headers': headers,
                'status_label': section_data['status_label']
            }

        except Exception as e:
            section_data['status_label'].config(text="Error", fg='red')
            self.log(f"Section {section_num}: ✗ ERROR - {str(e)}")
            return None

    def _do_http_request(self, request_data):
        """Perform the actual HTTP request in a background thread"""
        section_num = request_data['section_num']
        try:
            response = requests.post(
                request_data['url'],
                json=request_data['json_data'],
                headers=request_data['headers'],
                verify=True,
                timeout=30
            )
            return {
                'section_num': section_num,
                'status_code': response.status_code,
                'response': response,
                'error': None
            }
        except requests.exceptions.RequestException as e:
            return {
                'section_num': section_num,
                'status_code': None,
                'response': None,
                'error': f"NETWORK ERROR - {str(e)}"
            }
        except Exception as e:
            return {
                'section_num': section_num,
                'status_code': None,
                'response': None,
                'error': str(e)
            }

    def _handle_response(self, result):
        """Handle HTTP response on main thread (thread-safe UI update)"""
        section_num = result['section_num']
        section_data = self.sections[section_num - 1].section_data

        if result['error']:
            section_data['status_label'].config(text="Network Error", fg='red')
            self.log(f"Section {section_num}: ✗ {result['error']}")
            return

        response = result['response']

        if response.status_code == 200:
            try:
                resp_json = response.json()
                has_error = False
                error_msg = ""
                success_msg = ""

                for _, market_data in resp_json.items():
                    if isinstance(market_data, dict):
                        status = market_data.get('status', '')
                        if status == 'FAIL':
                            has_error = True
                            error_code = market_data.get('error', 'Unknown')
                            exception = market_data.get('exception', {})
                            exc_id = exception.get('id', '')
                            exc_msg = exception.get('message', '')
                            error_msg = f"{error_code} ({exc_id})"
                            if exc_msg:
                                error_msg += f": {exc_msg[:80]}..."
                        elif status == 'SUCCESS':
                            offer_ids = market_data.get('offerIds', {})
                            if offer_ids:
                                success_msg = f"Offer IDs: {offer_ids}"

                if has_error:
                    section_data['status_label'].config(text="FAILED", fg='red')
                    self.log(f"Section {section_num}: ✗ BET FAILED")
                    self.log(f"Section {section_num}: Error: {error_msg}")
                else:
                    section_data['status_label'].config(text="✓ SUCCESS", fg='green')
                    self.log(f"Section {section_num}: ✓ BET SUCCESS")
                    if success_msg:
                        self.log(f"Section {section_num}: {success_msg}")

            except json.JSONDecodeError:
                section_data['status_label'].config(text="Success", fg='green')
                self.log(f"Section {section_num}: ✓ Request sent (Status: 200)")
                self.log(f"Section {section_num}: Response: {response.text[:150]}...")
        else:
            section_data['status_label'].config(text=f"HTTP {response.status_code}", fg='red')
            self.log(f"Section {section_num}: ✗ HTTP ERROR (Status: {response.status_code})")

            try:
                error_data = response.json()
                self.log(f"Section {section_num}: {json.dumps(error_data, indent=2)[:300]}...")
            except:
                self.log(f"Section {section_num}: {response.text[:200]}...")
    
    def send_single_request_async(self, section_num):
        """Send a single section request asynchronously (for button clicks)"""
        request_data = self.send_request(section_num)
        if request_data:
            future = self.executor.submit(self._do_http_request, request_data)
            self._check_single_future(future)

    def _check_single_future(self, future):
        """Check if single future is done, update UI when complete"""
        if future.done():
            try:
                result = future.result()
                self._handle_response(result)
            except Exception as e:
                self.log(f"Error: {str(e)}")
        else:
            # Check again in 10ms
            self.root.after(10, lambda: self._check_single_future(future))

    def log(self, message):
        """Add message to common log (thread-safe)"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"
        # Schedule UI update on main thread
        self.root.after(0, lambda: self._append_log(log_message))

    def _append_log(self, message):
        """Actually append to log (must be called from main thread)"""
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
    
    def clear_log(self):
        """Clear the common log"""
        self.log_text.delete("1.0", tk.END)

    def apply_global_values(self):
        """Apply global price and size to all sections"""
        global_price = self.global_price_var.get().strip()
        global_size = self.global_size_var.get().strip()

        if not global_price and not global_size:
            messagebox.showwarning("Warning", "Enter at least Price or Size to apply!")
            return

        updated = []
        for i, section_frame in enumerate(self.sections):
            section_data = section_frame.section_data
            if global_price:
                section_data['price_var'].set(global_price)
            if global_size:
                section_data['size_var'].set(global_size)
            updated.append(str(i + 1))

        msg = f"Applied to Sections {', '.join(updated)}:"
        if global_price:
            msg += f" Price={global_price}"
        if global_size:
            msg += f" Size={global_size}"
        self.log(msg)

    def on_closing(self):
        """Clean up resources when window is closed"""
        self.is_running = False
        if self.pending_task_id:
            self.root.after_cancel(self.pending_task_id)
            self.pending_task_id = None
        self.executor.shutdown(wait=False)
        self.root.destroy()

    def toggle_task(self):
        """Toggle between start and stop"""
        if self.is_running:
            self.stop_task()
        else:
            self.start_task()

    def start_task(self):
        """Start the task: loop forever sending Section 1 & 4, then Section 2 & 3"""
        # Validate delay value
        try:
            delay_ms = int(self.delay_var.get())
            if delay_ms < 0:
                delay_ms = 0
        except ValueError:
            messagebox.showwarning("Warning", "Please enter a valid delay in milliseconds!")
            return

        self.is_running = True
        self.start_stop_button.config(text="■ STOP", bg='#f44336')
        self.global_status.config(text="Running...", fg='blue')
        self.log("=== Global Task Started (Loop Mode) ===")

        # Start the loop
        self.run_cycle_part1()

    def run_cycle_part1(self):
        """Part 1 of cycle: Send Section 1 & 4 in parallel, then schedule Part 2"""
        if not self.is_running:
            return

        # Get current delay value (allows changing delay while running)
        try:
            delay_ms = int(self.delay_var.get())
            if delay_ms < 0:
                delay_ms = 0
        except ValueError:
            delay_ms = 500

        # Prepare requests for Section 1 and Section 4
        self.log("Sending Section 1 & Section 4...")
        request_data_1 = self.send_request(1)
        request_data_4 = self.send_request(4)

        # Send both requests in parallel using thread pool
        requests_to_send = [r for r in [request_data_1, request_data_4] if r is not None]

        if requests_to_send:
            # Submit both requests to thread pool simultaneously
            futures = [self.executor.submit(self._do_http_request, req) for req in requests_to_send]

            # Check for completion without blocking UI
            self._wait_for_futures(futures, delay_ms, self.run_cycle_part2)
        else:
            # No valid requests, just schedule next part
            self.pending_task_id = self.root.after(delay_ms, self.run_cycle_part2)

    def run_cycle_part2(self):
        """Part 2 of cycle: Send Section 2 & 3 in parallel, then loop back to Part 1"""
        if not self.is_running:
            return

        # Get current delay value
        try:
            delay_ms = int(self.delay_var.get())
            if delay_ms < 0:
                delay_ms = 0
        except ValueError:
            delay_ms = 500

        # Prepare requests for Section 2 and Section 3
        self.log("Sending Section 2 & Section 3...")
        request_data_2 = self.send_request(2)
        request_data_3 = self.send_request(3)

        # Send both requests in parallel using thread pool
        requests_to_send = [r for r in [request_data_2, request_data_3] if r is not None]

        if requests_to_send:
            # Submit both requests to thread pool simultaneously
            futures = [self.executor.submit(self._do_http_request, req) for req in requests_to_send]

            # Check for completion without blocking UI
            self._wait_for_futures(futures, delay_ms, self.run_cycle_part1)
        else:
            # No valid requests, just schedule next part
            self.pending_task_id = self.root.after(delay_ms, self.run_cycle_part1)

    def _wait_for_futures(self, futures, delay_ms, next_callback):
        """Non-blocking wait for futures to complete, then schedule next step"""
        all_done = all(f.done() for f in futures)

        if all_done:
            # Process results on main thread
            for future in futures:
                try:
                    result = future.result()
                    self._handle_response(result)
                except Exception as e:
                    self.log(f"Error processing result: {str(e)}")

            # Schedule next part after delay
            if self.is_running:
                self.log(f"Waiting {delay_ms}ms...")
                self.pending_task_id = self.root.after(delay_ms, next_callback)
        else:
            # Check again in 10ms (keeps UI responsive)
            self.pending_task_id = self.root.after(10, lambda: self._wait_for_futures(futures, delay_ms, next_callback))

    def stop_task(self):
        """Stop the running task"""
        if self.pending_task_id:
            self.root.after_cancel(self.pending_task_id)
            self.pending_task_id = None

        self.is_running = False
        self.start_stop_button.config(text="▶ START", bg='#4CAF50')
        self.global_status.config(text="Stopped", fg='orange')
        self.log("=== Global Task Stopped ===")

def main():
    root = tk.Tk()
    app = RequestSenderApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
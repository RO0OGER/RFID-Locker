import tkinter as tk
from tkinter import messagebox
import threading
import random
import csv
import queue
import os
import time
import psutil
from paho.mqtt import client as mqtt_client
import keyboard  # Import the keyboard library

class ApplicationLocker:

    def __init__(self, root):
        self.root = root
        self.root.title("Application Locker")
        self.master_password = "1234"

        # Application name and password input fields
        self.app_label = tk.Label(root, text="RFID MANAGER")
        self.app_label.pack(pady=5)

        # Application name entry field
        self.app_name_label = tk.Label(root, text="Application Name (without .exe):")
        self.app_name_label.pack(pady=5)
        self.app_entry = tk.Entry(root)
        self.app_entry.pack(pady=5)

        # Register card button
        self.register_button = tk.Button(root, text="Register Card", command=self.register_card)
        self.register_button.pack(pady=20)

        # Remove application entry and button
        self.remove_app_label = tk.Label(root, text="Remove Application Name (without .exe):")
        self.remove_app_label.pack(pady=5)
        self.remove_app_entry = tk.Entry(root)
        self.remove_app_entry.pack(pady=5)
        self.remove_button = tk.Button(root, text="Remove Application", command=self.remove_application)
        self.remove_button.pack(pady=10)

        # MQTT settings
        self.broker = '192.168.3.33'
        self.port = 1883
        self.client_id = f'python-mqtt-{random.randint(0, 1000)}'
        self.topic = "IOE/widmerroger/RFID"

        # Queue to store card numbers
        self.card_queue = queue.Queue()

        # List of applications to monitor
        self.applications = self.load_applications()

        # Start MQTT client in a new thread
        self.mqtt_thread = threading.Thread(target=self.run_mqtt, daemon=True)
        self.mqtt_thread.start()

        # Start monitoring applications
        self.start_monitoring()

        # Bind the key combination Del+End to start_monitoring using keyboard library
        keyboard.add_hotkey('delete+end', self.handle_hotkey)

    def handle_hotkey(self):
        self.start_monitoring()
        print("Monitoring started.")  # Print message to console when monitoring starts

    def register_card(self):
        app_name = self.app_entry.get().strip()
        if not app_name:
            messagebox.showwarning("Warning", "Please enter an application name.")
            return
        
        if self.is_app_registered(app_name):
            messagebox.showerror("Error", "Application is already registered with another card.")
            return
        
        self.send(self.client, "IOE/widmerroger/RFID_SCRIPT", "Please scan your card")
        threading.Thread(target=self.wait_for_card_and_register, args=(app_name,), daemon=True).start()
        
    def wait_for_card_and_register(self, app_name):
        cardnumber = self.card_queue.get(block=True)  # Wait until a card number is received
        if not cardnumber:
            messagebox.showerror("Error", "Failed to retrieve card number.")
            return
        self.save_card_app_pair(cardnumber, app_name)
        messagebox.showinfo("Register Card", f"Card number: {cardnumber} registered to application: {app_name}")
        self.monitor_application(app_name)  # Start monitoring the application immediately after registration

    def send(self, client: mqtt_client, topic: str, message: str):
        result = client.publish(topic, message)
        status = result[0]
        if status == 0:
            print(f"Sent `{message}` to topic `{topic}`")
        else:
            print(f"Failed to send message to topic `{topic}`")

    def subscribe(self, client: mqtt_client):
        def on_message(client, userdata, msg):
            payload = msg.payload.decode()
            print(f"Received `{payload}` from `{msg.topic}` topic")
            self.card_queue.put(payload)
            time.sleep(1)

        client.subscribe(self.topic)
        client.on_message = on_message

    def connect_mqtt(self):
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print("Connected to MQTT Broker!")
            else:
                print(f"Failed to connect, return code {rc}")

        self.client = mqtt_client.Client(self.client_id)
        self.client.on_connect = on_connect
        self.client.connect(self.broker, self.port)
        return self.client

    def run_mqtt(self):
        client = self.connect_mqtt()
        self.subscribe(client)
        client.loop_start()

    def save_card_app_pair(self, cardnumber, app_name):
        with open('rfid_pairs.csv', 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([cardnumber, app_name])
        self.applications.append(app_name)

    def is_app_registered(self, app_name):
        try:
            with open('rfid_pairs.csv', 'r') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if len(row) > 1 and row[1] == app_name:
                        return True
        except FileNotFoundError:
            pass
        return False

    def remove_app_entry_by_name(self, app_name):
        found = False
        try:
            with open('rfid_pairs.csv', 'r') as csvfile:
                rows = list(csv.reader(csvfile))
            with open('rfid_pairs.csv', 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                for row in rows:
                    if len(row) > 1 and row[1] != app_name:
                        writer.writerow(row)
                    else:
                        found = True
        except FileNotFoundError:
            pass
        return found
        
    def remove_application(self):
        app_name = self.remove_app_entry.get().strip()
        if not app_name:
            messagebox.showwarning("Warning", "Please enter an application name to remove.")
            return

        if not self.remove_app_entry_by_name(app_name):
            messagebox.showerror("Error", "Application not found.")
        else:
            messagebox.showinfo("Remove Application", f"Application {app_name} removed.")

    def monitor_application(self, app_name):
        while True:
            try:
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['name'] and proc.info['name'].lower() == f'{app_name}.exe':
                        proc.terminate()  # Terminate the application process
                        self.lock_application(app_name)
                        return
                time.sleep(1)
            except Exception as e:
                print(f"Error monitoring application: {e}")
                return

    def lock_application(self, app_name):
        lock_window = tk.Toplevel(self.root)
        lock_window_label = tk.Label(lock_window, text="Please scan your card to unlock the application")
        lock_window_label.pack(pady=10)
        lock_window.title(f"{app_name.capitalize()}")
        
        card_id = self.wait_until_card_is_near()
        if self.is_card_registered(card_id):
            self.unlock_application(lock_window, card_id, app_name)
        else:
            messagebox.showerror("Error", "Card is not registered.")
            lock_window.destroy()

    def unlock_application(self, lock_window, card_id, app_name):
        if card_id == self.get_registered_card_id(app_name):
            os.system(f"start {app_name}.exe")
            print(f"Unlocked {app_name}")
            lock_window.destroy()
        else:
            time.sleep(0.5)
            command = "start microsoft.windows.camera:"
            command2 = "taskkill /im WindowsCamera.exe /t /f"
            os.system(command)
            time.sleep(1.5)
            os.system(command2)
            command3 = "rundll32.exe user32.dll,LockWorkStation"
            os.system(command3)
            lock_window.destroy()

    def start_monitoring(self):
        for app in self.applications:
            threading.Thread(target=self.monitor_application, args=(app,), daemon=True).start()

    def wait_until_card_is_near(self):
        self.send(self.client, "IOE/widmerroger/RFID_SCRIPT", "Please scan your card")
        card_id = self.card_queue.get(block=True)  # Wait until a card number is received
        return card_id

    def is_card_registered(self, card_id):
        try:
            with open('rfid_pairs.csv', 'r') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if len(row) > 0 and row[0] == card_id:
                        return True
        except FileNotFoundError:
            pass
        return False
    
    def get_registered_card_id(self, app_name):
        try:
            with open('rfid_pairs.csv', 'r') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if len(row) > 1 and row[1] == app_name:
                        return row[0]
        except FileNotFoundError:
            pass
        return None

    def load_applications(self):
        try:
            with open('rfid_pairs.csv', 'r') as csvfile:
                reader = csv.reader(csvfile)
                return [row[1] for row in reader if len(row) > 1]
        except FileNotFoundError:
            return []

if __name__ == "__main__":
    root = tk.Tk()
    app = ApplicationLocker(root)
    root.mainloop()

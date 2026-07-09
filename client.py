import socket
import json
import threading
import time
import sys

class SudokuClient:
    def __init__(self, host='127.0.0.1', port=5555):
        self.host = host
        self.port = port
        self.board = []
        self.solution = []
        self.player_board = [] # Track current inputs
        self.mode = None
        self.difficulty = None
        
        # Timer variables
        self.time_remaining = 0
        self.stopwatch_seconds = 0
        self.game_over = False
        self.server_conn = None

    def start_menu(self):
        print("=== WELCOME TO PYTHON SUDOKU ===")
        print("Select Mode:\n1. Singleplayer\n2. Multiplayer")
        mode_choice = input("Choice (1-2): ").strip()
        self.mode = "single" if mode_choice == "1" else "multi"

        print("\nSelect Difficulty:\n1. Easy (20 min countdown for multi)\n2. Normal (30 min countdown for multi)\n3. Hard (40 min countdown for multi)")
        diff_choice = input("Choice (1-3): ").strip()
        diff_map = {"1": "Easy", "2": "Normal", "3": "Hard"}
        self.difficulty = diff_map.get(diff_choice, "Normal")

        self.connect_to_server()

    def connect_to_server(self):
        try:
            self.server_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_conn.connect((self.host, self.port))
            
            # Send Game Request Config
            request = {"mode": self.mode, "difficulty": self.difficulty}
            self.server_conn.sendall(json.dumps(request).encode('utf-8'))
            
            if self.mode == "single":
                response = self.server_conn.recv(4096).decode('utf-8')
                data = json.loads(response)
                self.setup_game_data(data["board"], data["solution"])
                self.start_singleplayer_flow()
            else:
                print("\n[MATCHMAKING] Waiting for an opponent to join...")
                response = self.server_conn.recv(4096).decode('utf-8')
                data = json.loads(response)
                if data.get("status") == "matched":
                    print("[MATCH FOUND] Game Starting!")
                    self.time_remaining = data["timer"]
                    self.setup_game_data(data["board"], data["solution"])
                    self.start_multiplayer_flow()
                    
        except Exception as e:
            print(f"Could not connect or communicate with the system server: {e}")
            sys.exit(1)

    def setup_game_data(self, board_str, solution_str):
        # Convert strings into indexable 9x9 grids
        self.board = [list(board_str[i:i+9]) for i in range(0, 81, 9)]
        self.player_board = [list(board_str[i:i+9]) for i in range(0, 81, 9)]
        self.solution = [list(solution_str[i:i+9]) for i in range(0, 81, 9)]

    def print_grid(self):
        """Renders grid configuration cleanly to CLI"""
        print("\n" + "="*29)
        for i, row in enumerate(self.player_board):
            row_display = []
            for j, val in enumerate(row):
                char = val if val != '.' else ' '
                if j in [3, 6]:
                    row_display.append("| " + char)
                else:
                    row_display.append(char)
            print(" " + "  ".join(row_display))
            if i in [2, 5]:
                print("---+---------+---------+---")
        print("="*29)

    # --- SINGLEPLAYER MODULE ---
    def start_singleplayer_flow(self):
        use_watch = input("Enable optional tracking stopwatch? (y/n): ").lower().strip() == 'y'
        if use_watch:
            threading.Thread(target=self.stopwatch_thread, daemon=True).start()
        
        self.gameplay_loop(show_stopwatch=use_watch)

    def stopwatch_thread(self):
        while not self.game_over:
            time.sleep(1)
            self.stopwatch_seconds += 1

    # --- MULTIPLAYER MODULE ---
    def start_multiplayer_flow(self):
        # Start mandatory server sync listener and decrement timer thread
        threading.Thread(target=self.countdown_timer_thread, daemon=True).start()
        threading.Thread(target=self.listen_server_match_updates, daemon=True).start()
        self.gameplay_loop(show_countdown=True)

    def countdown_timer_thread(self):
        while self.time_remaining > 0 and not self.game_over:
            time.sleep(1)
            self.time_remaining -= 1
        if self.time_remaining <= 0 and not self.game_over:
            self.game_over = True
            print("\n[TIME'S UP] Match limit hit! You did not finish in time.")
            self.server_conn.close()

    def listen_server_match_updates(self):
        try:
            while True:
                data = self.server_conn.recv(1024).decode('utf-8')
                if not data: break
                update = json.loads(data)
                
                if update.get("status") == "win":
                    self.game_over = True
                    print("\n🏆 [VICTORY] You completed the puzzle first! You win!")
                    break
                elif update.get("status") == "lose":
                    self.game_over = True
                    print("\n❌ [DEFEAT] Your opponent completed their puzzle first! Game over.")
                    break
                elif update.get("status") == "win_forfeit":
                    self.game_over = True
                    print("\n🏆 [WIN BY FORFEIT] Your opponent disconnected or left early! You win!")
                    break
        except: pass

    # --- ENGINE INPUT CORE ---
    def gameplay_loop(self, show_stopwatch=False, show_countdown=False):
        while not self.game_over:
            self.print_grid()
            if show_stopwatch:
                mins, secs = divmod(self.stopwatch_seconds, 60)
                print(f"⏱️ Time elapsed: {mins:02d}:{secs:02d}")
            if show_countdown:
                mins, secs = divmod(self.time_remaining, 60)
                print(f"⏰ Mandatory Time Remaining: {mins:02d}:{secs:02d}")

            print("\nEnter move format (Row Column Value) e.g., '1 5 7'")
            print("Type 'check' to verify victory or 'exit' to quit.")
            move = input("Input: ").strip().lower()

            if move == 'exit':
                self.game_over = True
                break
            elif move == 'check':
                if self.player_board == self.solution:
                    if self.mode == "multi":
                        # Inform server instantly to check wins
                        self.server_conn.sendall(json.dumps({"status": "solved"}).encode('utf-8'))
                        # Wait briefly for server evaluation callback thread response
                        time.sleep(1)
                    else:
                        self.game_over = True
                        print("\n🎉 Congratulations! You accurately solved the Sudoku puzzle!")
                else:
                    print("\n⚠️ The board is either incomplete or has errors. Keep trying!")
            else:
                try:
                    r, c, v = move.split()
                    row, col, val = int(r) - 1, int(c) - 1, v
                    
                    # Validate coordinate boundaries
                    if 0 <= row < 9 and 0 <= col < 9 and val.isdigit() and 1 <= int(val) <= 9:
                        if self.board[row][col] == '.':
                            self.player_board[row][col] = val
                        else:
                            print("\n[ERROR] That cell contains an immutable original starting clue.")
                    else:
                        print("\n[ERROR] Invalid parameters. Coordinates must be 1-9; Values 1-9.")
                except ValueError:
                    print("\n[ERROR] Bad formatting syntax parse. Please match row-column-value layout.")

if __name__ == "__main__":
    # Change IP to your server address if running over external networks
    client = SudokuClient(host='127.0.0.1', port=5555)
    client.start_menu()

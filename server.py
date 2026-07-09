import socket
import threading
import sqlite3
import random
import json
import time

# --- DATABASE SETUP ---
DB_NAME = "sudoku_pool.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''CREATE TABLE IF NOT EXISTS un_used (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        difficulty TEXT,
                        board TEXT,
                        solution TEXT)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS used (
                        id INTEGER,
                        difficulty TEXT,
                        board TEXT,
                        solution TEXT)''')
    conn.commit()

    # Populate dummy boards if completely empty (1000 per difficulty)
    cursor.execute("SELECT COUNT(*) FROM un_used")
    count_unused = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM used")
    count_used = cursor.fetchone()[0]
    
    if count_unused == 0 and count_used == 0:
        print("Populating database with 3000 template puzzles...")
        difficulties = ['Easy', 'Normal', 'Hard']
        
        # Sample base valid boards for generation placeholder
        sample_sol = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
        sample_board = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"

        for diff in difficulties:
            for i in range(1000):
                # In a real app, use a sudoku generator or unique dataset here
                cursor.execute("INSERT INTO un_used (difficulty, board, solution) VALUES (?, ?, ?)",
                               (diff, sample_board, sample_sol))
        conn.commit()
    conn.close()

def get_daily_puzzle(difficulty):
    """Fetches a board, moves it to used, handles 1000-day recycling loop"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Check if we have puzzles left in un_used
    cursor.execute("SELECT id, board, solution FROM un_used WHERE difficulty = ? LIMIT 1", (difficulty,))
    row = cursor.fetchone()
    
    if not row:
        print(f"All {difficulty} puzzles used! Cycling the 'used' pool back to 'un_used'.")
        # Recycle pool loop
        cursor.execute("INSERT INTO un_used (id, difficulty, board, solution) SELECT id, difficulty, board, solution FROM used WHERE difficulty = ?", (difficulty,))
        cursor.execute("DELETE FROM used WHERE difficulty = ?", (difficulty,))
        conn.commit()
        
        # Re-fetch
        cursor.execute("SELECT id, board, solution FROM un_used WHERE difficulty = ? LIMIT 1", (difficulty,))
        row = cursor.fetchone()
        
    p_id, board, solution = row
    
    # Move to used table
    cursor.execute("INSERT INTO used (id, difficulty, board, solution) VALUES (?, ?, ?, ?)", (p_id, difficulty, board, solution))
    cursor.execute("DELETE FROM un_used WHERE id = ?", (p_id,))
    conn.commit()
    conn.close()
    
    return board, solution

# --- MULTIPLAYER MATCHMAKING SERVER ---
# Queues mapped by difficulty: {'Easy': [conn1, conn2...], 'Normal': [], 'Hard': []}
lobby_queues = {'Easy': [], 'Normal': [], 'Hard': []}
lobby_lock = threading.Lock()

def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected.")
    try:
        # Receive handshake config from client: {"mode": "single/multi", "difficulty": "Easy/Normal/Hard"}
        data = conn.recv(1024).decode('utf-8')
        if not data: return
        request = json.loads(data)
        
        difficulty = request.get("difficulty", "Normal")
        
        if request.get("mode") == "single":
            board, solution = get_daily_puzzle(difficulty)
            conn.sendall(json.dumps({"board": board, "solution": solution}).encode('utf-8'))
            conn.close()
            
        elif request.get("mode") == "multi":
            with lobby_lock:
                lobby_queues[difficulty].append(conn)
                print(f"[LOBBY] Player added to {difficulty} queue. Total size: {len(lobby_queues[difficulty])}")
            
            # Check if match can be made
            matchmake(difficulty)
            
    except Exception as e:
        print(f"[SERVER ERROR] Exception handling client {addr}: {e}")
        conn.close()

def matchmake(difficulty):
    with lobby_lock:
        if len(lobby_queues[difficulty]) >= 2:
            player1 = lobby_queues[difficulty].pop(0)
            player2 = lobby_queues[difficulty].pop(0)
            
            # Serve identical shared puzzle to both users
            board, solution = get_daily_puzzle(difficulty)
            
            # Timers: Easy=20 min, Normal=30 min, Hard=40 min
            timer_limits = {"Easy": 1200, "Normal": 1800, "Hard": 2400}
            duration = timer_limits.get(difficulty, 1800)
            
            payload = {
                "status": "matched",
                "board": board,
                "solution": solution,
                "timer": duration
            }
            
            # Spin up a live dynamic match referee thread
            threading.Thread(target=run_match, args=(player1, player2, payload), daemon=True).start()

def run_match(p1, p2, match_data):
    """Pipes events between 2 competing clients until completion or timeout"""
    p1.sendall(json.dumps(match_data).encode('utf-8'))
    p2.sendall(json.dumps(match_data).encode('utf-8'))
    
    def listen_player(player_conn, opponent_conn, player_label):
        try:
            while True:
                msg = player_conn.recv(1024).decode('utf-8')
                if not msg: break
                event = json.loads(msg)
                
                if event.get("status") == "solved":
                    # Broadcast immediate win to sender and lose to opponent
                    player_conn.sendall(json.dumps({"status": "win"}).encode('utf-8'))
                    opponent_conn.sendall(json.dumps({"status": "lose"}).encode('utf-8'))
                    break
        except:
            # If a player disconnects, opponent automatically wins
            try: opponent_conn.sendall(json.dumps({"status": "win_forfeit"}).encode('utf-8'))
            except: pass
        finally:
            player_conn.close()
            opponent_conn.close()

    threading.Thread(target=listen_player, args=(p1, p2, "P1"), daemon=True).start()
    threading.Thread(target=listen_player, args=(p2, p1, "P2"), daemon=True).start()

def start_server():
    init_db()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', 5555))
    server.listen()
    print("[SERVER STARTED] Listening on port 5555...")
    
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    start_server()

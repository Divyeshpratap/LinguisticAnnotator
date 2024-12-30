from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure key in production

DATABASE = 'database.db'
CSV_FILE = 'verbnet_tagged_nate_formatted.csv'

# Predefined users
USERS = ['dsingh27', 'dgusain', 'inwogu', 'nmbeers', 'ahendric', 'fbulgare']

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DATABASE):
        conn = get_db_connection()
        cursor = conn.cursor()
        # Read CSV
        df = pd.read_csv(CSV_FILE)
        # Create table with appropriate columns
        columns = df.columns.tolist()
        column_defs = []
        for col in columns:
            if col == 'S.No.':
                column_defs.append(f'"{col}" INTEGER PRIMARY KEY')
            else:
                column_defs.append(f'"{col}" TEXT')
        create_table_sql = f"CREATE TABLE data ({', '.join(column_defs)});"
        cursor.execute(create_table_sql)
        # Insert data
        for index, row in df.iterrows():
            values = [row[col] for col in columns]
            placeholders = ','.join(['?'] * len(columns))
            # Quote column names separately
            quoted_columns = ['"{}"'.format(col) for col in columns]
            insert_sql = f'INSERT INTO data ({", ".join(quoted_columns)}) VALUES ({placeholders})'
            cursor.execute(insert_sql, values)
        # Add response columns for predefined users
        for user in USERS:
            response_column = f"{user}_response"
            cursor.execute(f'ALTER TABLE data ADD COLUMN "{response_column}" TEXT')
        conn.commit()
        conn.close()

def get_class_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT "Class" FROM data')
    classes = [row['Class'] for row in cursor.fetchall()]
    conn.close()
    # Sort classes numerically in ascending order
    try:
        sorted_classes = sorted(classes, key=lambda x: int(x))
    except ValueError:
        # If classes are not purely numeric, sort lexicographically
        sorted_classes = sorted(classes)
    return sorted_classes

def is_class_completed(conn, user, class_number):
    cursor = conn.cursor()
    # Fetch all examples in the class
    cursor.execute('SELECT COUNT(*) as total FROM data WHERE "Class" = ?', (class_number,))
    total = cursor.fetchone()['total']
    # Fetch all annotated examples by the user in the class
    response_column = f"{user}_response"
    cursor.execute(f'SELECT COUNT(*) as annotated FROM data WHERE "Class" = ? AND "{response_column}" IS NOT NULL AND "{response_column}" != ""', (class_number,))
    annotated = cursor.fetchone()['annotated']
    return annotated >= total

@app.route('/')
def select_user():
    return render_template('select_user.html', users=USERS)

@app.route('/select_user', methods=['POST'])
def handle_select_user():
    selected_user = request.form.get('username')
    if selected_user not in USERS:
        return render_template('select_user.html', users=USERS, error="Invalid user selected.")
    
    # Add the user to the USERS list if not already present
    if selected_user not in USERS:
        USERS.append(selected_user)
    
    session['username'] = selected_user
    
    # Connect to the database
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if the response column for the user exists
    cursor.execute("PRAGMA table_info(data);")
    columns = [row['name'] for row in cursor.fetchall()]
    response_column = f"{selected_user}_response"
    
    if response_column not in columns:
        # Add the response column for the new user
        try:
            cursor.execute(f'ALTER TABLE data ADD COLUMN "{response_column}" TEXT')
            conn.commit()
            print(f"Added column '{response_column}' to 'data' table.")
        except sqlite3.OperationalError as e:
            print(f"Error adding column: {e}")
            conn.close()
            return render_template('select_user.html', users=USERS, error="Failed to add new user.")
    
    conn.close()
    return redirect(url_for('annotate', page=1))

@app.route('/annotate', methods=['GET', 'POST'])
def annotate():
    if 'username' not in session:
        return redirect(url_for('select_user'))
    username = session['username']
    conn = get_db_connection()
    cursor = conn.cursor()
    # Get the list of classes sorted in ascending order
    class_list = get_class_list()
    total_classes = len(class_list)
    per_page = 1  # One class per page

    if request.method == 'POST':
        # Get current page number
        page = int(request.form.get('page', 1))
        if page < 1 or page > total_classes:
            page = 1  # Reset to first page if out of bounds

        # Get class number for current page
        current_class = class_list[page - 1]

        # Get responses
        s_nos = request.form.getlist('s_no')
        responses = []
        for s_no in s_nos:
            response = request.form.get(f'response_{s_no}')
            if not response:
                # Handle missing response
                # Re-fetch the current class examples
                cursor.execute('SELECT * FROM data WHERE "Class" = ?', (current_class,))
                rows = cursor.fetchall()
                # Determine completion status for sidebar
                completed_classes = []
                for cls in class_list:
                    completed = is_class_completed(conn, username, cls)
                    completed_classes.append({'class_number': cls, 'completed': completed})
                conn.close()
                return render_template('annotate.html',
                                       error="Please select responses for all examples.",
                                       rows=rows,
                                       page=page,
                                       total=total_classes,
                                       per_page=per_page,
                                       username=username,
                                       class_number=current_class,
                                       classes=completed_classes)
            responses.append((s_no, response))
        # Save to database
        response_column = f"{username}_response"
        for s_no, response in responses:
            cursor.execute(f'UPDATE data SET "{response_column}" = ? WHERE "S.No." = ?', (response, s_no))
        conn.commit()

        # Check if all classes are completed
        all_completed = True
        for cls in class_list:
            if not is_class_completed(conn, username, cls):
                all_completed = False
                break

        if all_completed:
            conn.close()
            return render_template('complete.html')
        else:
            # If current class is the last class, redirect to first class
            if page == total_classes:
                conn.close()
                return redirect(url_for('annotate', page=1))
            else:
                # Redirect to next class
                page += 1
                conn.close()
                return redirect(url_for('annotate', page=page))
    else:
        # GET request, show annotations
        page = request.args.get('page', 1, type=int)
        if page < 1 or page > total_classes:
            page = 1  # Reset to first page if out of bounds
        # Get class number for current page
        current_class = class_list[page - 1]
        # Fetch all examples for the current class
        cursor.execute('SELECT * FROM data WHERE "Class" = ?', (current_class,))
        rows = cursor.fetchall()
        # Get user responses
        response_column = f"{username}_response"
        row_ids = [row['S.No.'] for row in rows]
        if row_ids:
            placeholders = ','.join(['?']*len(row_ids))
            query = f'SELECT "S.No.", "{response_column}" FROM data WHERE "S.No." IN ({placeholders})'
            cursor.execute(query, row_ids)
            responses = {row['S.No.']: row[response_column] for row in cursor.fetchall()}
        else:
            responses = {}
        # Determine completion status for sidebar
        completed_classes = []
        for cls in class_list:
            completed = is_class_completed(conn, username, cls)
            completed_classes.append({'class_number': cls, 'completed': completed})
        conn.close()
        return render_template('annotate.html',
                               rows=rows,
                               responses=responses,
                               page=page,
                               total=total_classes,
                               per_page=per_page,
                               username=username,
                               class_number=current_class,
                               classes=completed_classes)


@app.route('/complete')
def complete():
    if 'username' not in session:
        return redirect(url_for('select_user'))
    return render_template('complete.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('select_user'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

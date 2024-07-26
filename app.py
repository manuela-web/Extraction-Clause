from flask import Flask, request, render_template, session, redirect, url_for, Response
from pdf2docx import Converter
from asyncio import sleep
from flask_socketio import SocketIO
import fitz  
import threading
import os
import uuid
from docx2pdf import convert
from docx import Document
import spacy
from docx.enum.section import WD_SECTION_START
from docx.shared import Pt
import re
from PyPDF2 import PdfReader, PdfWriter
import sqlite3


app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Sostituisci con una chiave segreta casuale
socketIO = SocketIO(app)


# Variabile condivisa per mantenere l'id della stanza
shared_socketid = None
socketid_lock = threading.Lock()


# Creazione della connessione al database
conn = sqlite3.connect('C:\\Users\\utente\\Desktop\\pdfGPT\\pdf_GPT\\db\\clausole.db')
cursor = conn.cursor()

# Creazione della tabella se non esiste già
cursor.execute('''
    CREATE TABLE IF NOT EXISTS clausole (
        id INTEGER PRIMARY KEY,
        clausola TEXT NOT NULL,
        label TEXT
    )
''')
conn.commit()

# Funzione per ottenere i dati dal database SQLite
def get_data_from_database():
    connection = sqlite3.connect('C:\\Users\\utente\\Desktop\\pdfGPT\\pdf_GPT\\db\\clausole.db')
    cursor = connection.cursor()

    # Sostituisci 'nome_tabella' con il nome effettivo della tua tabella nel database
    query = 'SELECT * FROM clausole'
    cursor.execute(query)
    data = cursor.fetchall()

    connection.close()

    return data

@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('upload.html')


@app.route('/label.html')
def label_page():
    # Ottieni i dati dal database
    data = get_data_from_database()
    return render_template('label.html', data=data)


def get_num_pages(pdf_filename):
    pdf_document = fitz.open(pdf_filename)
    num_pages = pdf_document.page_count
    pdf_document.close()
    return num_pages


def extract_text_from_region(page, region):
    rect = fitz.Rect(region['x'], region['y'], region['x'] + region['width'], region['y'] + region['height'])
    text = page.get_text("text", clip=rect)
    return text



def process_pdf(pdf_filename, socketid, start_page, end_page, regex_pattern, region):
    global shared_socketid

    with socketid_lock:
        socketid = shared_socketid

    # Crea una nuova connessione e un nuovo cursore all'interno del thread
    thread_conn = sqlite3.connect('C:\\Users\\utente\\Desktop\\pdfGPT\\pdf_GPT\\db\\clausole.db')
    thread_cursor = thread_conn.cursor()

    total_pages = get_num_pages(pdf_filename)

    # Utilizza i valori di "Inizio" e "Fine" per specificare le pagine da convertire
    start_page = max(0, min(int(start_page), total_pages))
    end_page = max(start_page, min(int(end_page), total_pages))

    output_path = os.path.join('C:\\Users\\utente\\Desktop\\pdfGPT\\pdf_GPT', 'output.pdf')

    # Estrae solo le pagine specificate
    with open(pdf_filename, 'rb') as input_pdf, open(output_path, 'wb') as output_pdf:
        writer = PdfWriter()
        for page_num in range(start_page-1, end_page):
            writer.add_page(PdfReader(input_pdf).pages[page_num])
        writer.write(output_pdf)

    pdf_document = fitz.open(output_path)

    output_doc = Document()
   
    clauses = []
    # Crea una nuova connessione SQLite nel thread corrente
    with sqlite3.connect('C:\\Users\\utente\\Desktop\\pdfGPT\\pdf_GPT\\db\\clausole.db') as conn:
        cursor = conn.cursor()

    clause_pattern = re.compile(regex_pattern, re.DOTALL)

    for page_num in range(pdf_document.page_count):
        page = pdf_document.load_page(page_num)
        region_of_interest = {'x': region['x'], 'y': region['y'], 'width': region['width'], 'height': region['height']}
        region_text = extract_text_from_region(page, region_of_interest)

        # Aggiungi il testo estratto al documento di output
        output_doc.add_paragraph(region_text)

        matches = clause_pattern.findall(region_text)
        print(matches)
               
        for match in matches:
            cursor.execute("INSERT INTO clausole (clausola) VALUES (?)", (match,))
            conn.commit()
   
    pdf_document.close()
    word_output_path = os.path.join('C:\\Users\\utente\\Desktop\\pdfGPT\\pdf_GPT', 'output.docx')
    output_doc.save(word_output_path)

    socketIO.emit('update_progress', {'progress': 100}, room=socketid)
    print("Estrazione completata")  # Log aggiunto
    socketIO.emit('processing_complete', {'message': 'File PDF generato con successo!'}, room=socketid)


@app.route('/progress/<socketid>', methods=['POST'])
def progress(socketid):
    global shared_socketid
    app.logger.info('Received POST request to /progress')
    if request.method == 'POST':
        if 'pdfFile' in request.files:
            app.logger.info('PDF file found in request')
            pdf_file = request.files['pdfFile']
            if pdf_file.filename != '':
                app.logger.info('PDF file name: %s', pdf_file.filename)
                save_directory = 'C:\\Users\\utente\\Desktop\\pdfGPT\\pdf_GPT'
                os.makedirs(save_directory, exist_ok=True)
                save_path = os.path.join(save_directory, pdf_file.filename)
                pdf_file.save(save_path)
                app.logger.info('PDF file saved to %s', save_path)
                start_page = int(request.form.get('inizio', 0))
                end_page = int(request.form.get('fine', get_num_pages(save_path)))
                regex_pattern = request.form.get('regex', r'(?:(?<=^)|(?<=\n))\d+\.\s[^\d\n].*?(?=(?:\d+\.\s[^\d\n]|$))')
                region = {
                    'x': int(request.form.get('x', 0)),
                    'y': int(request.form.get('y', 115)),
                    'width': int(request.form.get('larghezza', 600)),
                    'height': int(request.form.get('altezza', 675))
                }
                threading.Thread(target=process_pdf, args=(save_path, socketid, start_page, end_page, regex_pattern, region)).start()
        else:
            app.logger.error('No PDF file found in request')

    return Response(status=204)

     
if __name__ == '__main__':
    socketIO.run(app, debug=True)




# Chiudi la connessione al database quando il tuo script termina
conn.close()



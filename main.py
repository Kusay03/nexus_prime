from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows any web page to read the data
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Database connection details (Connecting to your Podman container!)
DB_HOST = "host.containers.internal"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = "mysecretpassword" # Put your Postgres password here!

def get_db_connection():
    """This function opens the door to the database."""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor # This magically formats SQL rows into JSON dictionaries!
    )
    return conn

@app.get("/")
def home():
    return {"message": "Welcome to the Project Nexus API!"}

@app.get("/api/graph")
def get_graph_data():
    """This endpoint gets the Hacker/Server connection data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # We query the exact Boss Level View you built!
    query = """
        SELECT 
            src_data.attribute_value AS attacker,
            conn.relationship_type AS action,
            tgt_data.attribute_value AS target
        FROM vw_Graph_Connections conn
        JOIN vw_Entity_Master src_data 
            ON conn.source_entity_id = src_data.entity_id 
            AND src_data.attribute_name = 'Username'
        JOIN vw_Entity_Master tgt_data 
            ON conn.target_entity_id = tgt_data.entity_id 
            AND tgt_data.attribute_name = 'IP Address';
    """
    
    cursor.execute(query)
    data = cursor.fetchall() # Grab all the rows
    
    cursor.close()
    conn.close()
    
    return {"graph_connections": data}
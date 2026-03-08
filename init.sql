-- ==========================================
-- 1. SCHEMA GENERIQUE (EAV MODEL)
-- ==========================================
CREATE TABLE Companies (
    company_id SERIAL PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL
);

CREATE TABLE Entity_Types (
    type_id SERIAL PRIMARY KEY,
    company_id INT,
    type_name VARCHAR(100) NOT NULL,
    FOREIGN KEY (company_id) REFERENCES Companies(company_id) ON DELETE CASCADE
);

CREATE TABLE Attributes (
    attribute_id SERIAL PRIMARY KEY,
    type_id INT,
    attribute_name VARCHAR(100) NOT NULL,
    data_type VARCHAR(50) CHECK (data_type IN ('STRING', 'NUMBER', 'DATE')),
    FOREIGN KEY (type_id) REFERENCES Entity_Types(type_id) ON DELETE CASCADE
);

CREATE TABLE Entities (
    entity_id SERIAL PRIMARY KEY,
    type_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (type_id) REFERENCES Entity_Types(type_id) ON DELETE CASCADE
);

CREATE TABLE Values (
    value_id SERIAL PRIMARY KEY,
    entity_id INT,
    attribute_id INT,
    string_value VARCHAR(500),
    numeric_value DECIMAL(15, 2),
    date_value DATE,
    FOREIGN KEY (entity_id) REFERENCES Entities(entity_id) ON DELETE CASCADE,
    FOREIGN KEY (attribute_id) REFERENCES Attributes(attribute_id) ON DELETE CASCADE
);

CREATE TABLE Connections (
    connection_id SERIAL PRIMARY KEY,
    source_entity_id INT,
    target_entity_id INT,
    relationship_type VARCHAR(100) NOT NULL, 
    FOREIGN KEY (source_entity_id) REFERENCES Entities(entity_id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES Entities(entity_id) ON DELETE CASCADE
);

-- ==========================================
-- 2. DONNEES DE TEST (EXEMPLE CYBER)
-- ==========================================
INSERT INTO Companies (company_name) VALUES ('CyberGuard Inc.');
INSERT INTO Entity_Types (company_id, type_name) VALUES (1, 'User'), (1, 'Server');

INSERT INTO Attributes (type_id, attribute_name, data_type) VALUES 
(1, 'Username', 'STRING'),
(1, 'Threat Level', 'NUMBER'),
(2, 'IP Address', 'STRING');

INSERT INTO Entities (type_id) VALUES (1), (2);

-- Assignation des valeurs aux entités
INSERT INTO Values (entity_id, attribute_id, string_value) VALUES (1, 1, 'hacker_99'); 
INSERT INTO Values (entity_id, attribute_id, numeric_value) VALUES (1, 2, 85.5);       
INSERT INTO Values (entity_id, attribute_id, string_value) VALUES (2, 3, '192.168.0.1'); 

-- Création de la connexion réseau
INSERT INTO Connections (source_entity_id, target_entity_id, relationship_type) VALUES (1, 2, 'UNAUTHORIZED_ACCESS');

-- ==========================================
-- 3. THE MASTER VIEW (Control Plane)
-- ==========================================
-- Cette vue transforme le modèle EAV complexe en un format plat (Node A -> Action -> Node B)
CREATE OR REPLACE VIEW vw_Graph_Connections AS
SELECT 
    v_src.string_value AS attacker,
    v_dst.string_value AS target,
    c.relationship_type AS action
FROM Connections c
LEFT JOIN Values v_src ON c.source_entity_id = v_src.entity_id 
    AND v_src.attribute_id = (SELECT attribute_id FROM Attributes WHERE attribute_name = 'Username' LIMIT 1)
LEFT JOIN Values v_dst ON c.target_entity_id = v_dst.entity_id 
    AND v_dst.attribute_id = (SELECT attribute_id FROM Attributes WHERE attribute_name = 'IP Address' LIMIT 1);
"""Local UI review with a disposable database. Never uses warehouse.db."""
import os
from pathlib import Path
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
directory=tempfile.TemporaryDirectory()
os.environ.update(SLED_DATABASE=str(Path(directory.name)/'preview.db'),TURSO_DATABASE_URL='',TURSO_AUTH_TOKEN='',VERCEL='')
from app import app
from flask import abort,redirect,session,url_for
from models.repository import get_db

with app.app_context():
    db=get_db()
    for role in ('warehouse','purchasing'):
        db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',(role,role+'@preview.invalid','disabled',role))
    db.execute('UPDATE components SET stock=100,reserved=0')
    db.commit()

@app.route('/_review/<role>')
def local_review(role):
    if role not in ('admin','sales','technician','warehouse','purchasing','accountant'):
        abort(404)
    user=get_db().execute('SELECT * FROM users WHERE role=?',(role,)).fetchone()
    session.clear()
    session.update(user_id=user['id'],user_name='Kiểm thử '+role,role=role)
    return redirect(url_for('orders.create') if role=='sales' else url_for('inventory.index'))

if __name__=='__main__':
    app.run(host='127.0.0.1',port=5127,debug=False,use_reloader=False)

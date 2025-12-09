1:
venv\Scripts\activate

2:
pip install -r requirements.txt

3:
python manage.py migrate
or
python manage.py makemigrations

4:
python manage.py runserver

5:
http://127.0.0.1:8000/api/docs/swagger/

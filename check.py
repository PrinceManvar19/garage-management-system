from app import create_app
app = create_app()
app.config['TESTING'] = True
client = app.test_client()
with client.session_transaction() as sess:
    sess['role'] = 'admin'
    sess['customer_id'] = 'ADMIN001'
    sess['name'] = 'Owner 1'
    sess['phone'] = ''
    sess['user'] = {'id': 'ADMIN001', 'name': 'Owner 1', 'phone': '', 'role': 'admin'}
r = client.get('/admin')
print('Status:', r.status_code)
if r.status_code == 200:
    html = r.data.decode()
    for needle, label in [
        ('admin-stat-card warn', 'Pending stat card'),
        ('admin-stat-card success', 'Approved stat card'),
        ('admin-stat-card info', 'Completed stat card'),
        ('admin-stat-card done', 'Rejected stat card'),
        ('Total Bookings', 'Total Bookings label'),
        ('Pending', 'Pending label'),
        ('Approved', 'Approved label'),
        ('Completed', 'Completed label'),
        ('Rejected', 'Rejected label'),
        ('Vehicles in Garage', 'Vehicles section'),
    ]:
        print(('OK   ' if needle in html else 'MISS ') + label)
else:
    print('ERROR', r.status_code)
    print(r.data.decode()[:600])

from flask import Blueprint, request, redirect, url_for, session, render_template
from models.user import User, UserErrors


user_blueprint = Blueprint('users', __name__)


@user_blueprint.route('/register', methods=['POST', 'GET'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            User.register_user(email, password)
            session['email'] = email
            return email
        except UserErrors.UserError as e:
            return e.message

    return render_template('users/register.html')



@user_blueprint.route('/login', methods=['POST','GET'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            if User.is_login_valid(email, password):
                session['email'] = email
                return email
        except UserErrors.UserError as e:
            return e.message

    return render_template('users/login.html')


@user_blueprint.route('/logout')
def logout():
    session['email'] = None
    return redirect(url_for('users.login'))
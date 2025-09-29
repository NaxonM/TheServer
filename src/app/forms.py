from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, URLField
from wtforms.validators import DataRequired, Optional

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign In')

class ProxyUrlForm(FlaskForm):
    url = URLField('Remote URL', validators=[DataRequired()])
    filename = StringField('New Filename', validators=[Optional()])
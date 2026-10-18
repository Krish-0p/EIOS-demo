"""Host-administrator recovery: issue a private one-time token, never a password.

Run manually in the orchestrator container:
    python recover_password.py --username admin --issue-token
Paste the token into the login screen's “I have a recovery token” form.
"""
import argparse
import secrets

import auth
import db


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username',required=True)
    parser.add_argument('--issue-token',action='store_true',required=True)
    args=parser.parse_args()
    token=secrets.token_urlsafe(32)
    db.pool.open()
    try:
        with db.pool.connection() as conn:
            row=conn.execute('SELECT user_id FROM users WHERE username=%s AND NOT disabled',(args.username.strip().lower(),)).fetchone()
            if not row:
                parser.error('Enabled account not found')
            conn.execute('UPDATE password_reset_tokens SET used_at=NOW() WHERE user_id=%s AND used_at IS NULL',(row[0],))
            conn.execute("INSERT INTO password_reset_tokens(token_hash,user_id,expires_at) VALUES(%s,%s,NOW()+INTERVAL '30 minutes')",(auth.token_hash(token),row[0]))
            auth.audit(conn,'host-administrator','auth.recovery_issued',subject_id=row[0])
        print('Recovery token (expires in 30 minutes; deliver privately):')
        print(token)
    finally:
        db.pool.close()


if __name__=='__main__':
    main()

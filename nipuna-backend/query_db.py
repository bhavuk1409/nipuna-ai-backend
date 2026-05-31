import sys
from app.database import SyncSessionLocal
from app.models.user import User
from app.models.organization import Organization

def main():
    print("Database Query Script Started...")
    try:
        with SyncSessionLocal() as session:
            users = session.query(User).all()
            orgs = session.query(Organization).all()
            print(f"Total Users: {len(users)}")
            for u in users:
                print(f"USER: id={u.id}, email={u.email}, clerk={u.clerk_user_id}, org_id={u.org_id}, role={u.role}")
            print(f"Total Orgs: {len(orgs)}")
            for o in orgs:
                print(f"ORG: id={o.id}, name={o.name}, clerk_org_id={o.clerk_org_id}")
    except Exception as e:
        print(f"Database Query Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

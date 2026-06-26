# Nipuna AI - Workspace Architecture Diagram

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         User: bhavukagrawal1409@gmail.com               │
│                         (Authenticated via Clerk)                       │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
    ┌───────────▼──────────┐  ┌──────────▼──────────┐
    │   Workspace: Paytm   │  │  Workspace: Mahalaxmi│
    │   Role: Admin        │  │  Role: Admin         │
    └───────────┬──────────┘  └──────────┬──────────┘
                │                         │
                │ COMPLETELY ISOLATED     │
                │ Zero Data Overlap       │
                │                         │
                ▼                         ▼
```

---

## Workspace Isolation Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            WORKSPACE: PAYTM                             │
│                         org_id: abc-123-def                            │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ├─ Chats & Conversations
        │   ├─ Chat 1: "What's my cash flow?"
        │   ├─ Chat 2: "Show invoices for Jan 2026"
        │   └─ Chat 3: "Revenue analysis"
        │
        ├─ Integrations
        │   ├─ Gmail (connected)
        │   ├─ Tally (connected)
        │   └─ WhatsApp (pending)
        │
        ├─ AI Agents
        │   ├─ Paytm Financial Agent
        │   └─ Paytm Customer Support Agent
        │
        ├─ Team Members
        │   ├─ bhavuk@example.com (Admin)
        │   ├─ alice@paytm.com (Member)
        │   └─ bob@paytm.com (Viewer)
        │
        └─ Settings
            ├─ AI Credits: 85 remaining
            ├─ Plan: Free
            └─ Seats: 3/5 used

┌─────────────────────────────────────────────────────────────────────────┐
│                       WORKSPACE: MAHALAXMI ENTERPRISES                  │
│                         org_id: xyz-789-ghi                            │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ├─ Chats & Conversations
        │   └─ Chat 1: "Monthly expenses summary"
        │
        ├─ Integrations
        │   └─ Zoho Books (connected)
        │
        ├─ AI Agents
        │   └─ Mahalaxmi Business Agent
        │
        ├─ Team Members
        │   ├─ bhavuk@example.com (Admin)
        │   └─ carol@mahalaxmi.com (Member)
        │
        └─ Settings
            ├─ AI Credits: 100 remaining
            ├─ Plan: Free
            └─ Seats: 2/5 used
```

**Key Point:** Paytm's chats NEVER appear in Mahalaxmi, and vice versa!

---

## Data Flow: Workspace Switching

```
User clicks Workspace Switcher
         │
         ▼
┌──────────────────────────┐
│ Frontend: setActive()    │
│ → Clerk updates JWT      │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ JWT now contains:        │
│ • sub: user_id           │
│ • org_id: new_workspace  │◄─── This changes!
│ • iat, exp, etc.         │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ All API calls now use    │
│ new org_id automatically │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ Backend filters by:      │
│ WHERE org_id = new_id    │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ Only new workspace data  │
│ returned to frontend     │
└──────────────────────────┘
```

---

## Database Schema Overview

```sql
┌────────────────────────┐
│   organizations        │
├────────────────────────┤
│ id (UUID)             │◄────┐
│ clerk_org_id (unique) │     │
│ name                  │     │
│ plan                  │     │
│ ai_credits            │     │
└────────────────────────┘     │
                               │
                               │ Referenced by org_id
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ conversations  │  │ integrations   │  │ agents         │
├────────────────┤  ├────────────────┤  ├────────────────┤
│ id            │  │ id            │  │ id            │
│ org_id ───────┼──┤ org_id ───────┼──┤ org_id ───────┤
│ agent_id      │  │ provider      │  │ name          │
│ user_id       │  │ status        │  │ status        │
└────────────────┘  └────────────────┘  └────────────────┘
        │                      │                      │
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                               ▼
                        ALL QUERIES FILTER BY:
                        WHERE org_id = current_workspace
```

**Security:** Every table has `org_id` → No cross-workspace access possible!

---

## Role-Based Access Control (RBAC)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER IN WORKSPACE                            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                ┌──────────┴──────────┐
                │                     │
        ┌───────▼────────┐    ┌──────▼──────┐    ┌──────▼──────┐
        │     ADMIN      │    │   MEMBER    │    │   VIEWER    │
        └───────┬────────┘    └──────┬──────┘    └──────┬──────┘
                │                     │                   │
                │                     │                   │
   ┌────────────┼─────────────────────┼───────────────────┼─────────┐
   │            │                     │                   │         │
   ▼            ▼                     ▼                   ▼         │
Ask Nipuna   Team Mgmt           Ask Nipuna          View Only    │
Search Chat  Integrations        Search Chat         No Write     │
View Team    Create Agents       View Team           No Chat      │
Delete WS    Billing             (no admin)          (403 error)  │
             Full Control                                          │
                                                                   │
┌──────────────────────────────────────────────────────────────────┘
│
│  Backend Enforcement (dependencies.py):
│  ─────────────────────────────────────
│  • require_admin() → 403 if not admin
│  • require_chat_permission() → 403 if viewer
│  • get_current_org() → resolves org from JWT
│
│  Frontend Enforcement (shell.tsx):
│  ──────────────────────────────────
│  • userProfile.role fetched per workspace
│  • Nav items hidden for non-admins
│  • Role badge shown in profile tooltip
│
└───────────────────────────────────────────────────────────────────┘
```

---

## Team Invitation Flow

### For Existing Nipuna Users

```
Admin clicks "Invite Member"
         │
         ▼
┌──────────────────────────┐
│ Backend creates:         │
│ • Pending User row       │
│ • Alert notification     │
│ • Sends email            │
└───────────┬──────────────┘
            │
            ├─────────────────────────┐
            │                         │
            ▼                         ▼
┌──────────────────┐      ┌──────────────────┐
│ Email sent       │      │ In-app notif     │
│ with Join link   │      │ (bell icon)      │
└──────────────────┘      └────────┬─────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │ User sees:       │
                          │ [Accept] [Decline]│
                          └────────┬─────────┘
                                   │
                  ┌────────────────┴────────────────┐
                  │                                 │
                  ▼                                 ▼
         ┌─────────────────┐              ┌─────────────────┐
         │ User clicks     │              │ User clicks     │
         │ Accept          │              │ Decline         │
         └────────┬────────┘              └────────┬────────┘
                  │                                 │
                  ▼                                 ▼
         ┌─────────────────┐              ┌─────────────────┐
         │ • status=active │              │ • status=declined│
         │ • Added to Clerk│              │ • Removed from  │
         │ • Auto-switch   │              │   pending list  │
         └─────────────────┘              └─────────────────┘
```

### For New Users (No Account)

```
Admin clicks "Invite Member"
         │
         ▼
┌──────────────────────────┐
│ Backend:                 │
│ • Creates pending User   │
│ • Sends email with       │
│   sign-up link           │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ User receives email      │
│ Clicks sign-up link      │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ User signs up via Clerk  │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ Webhook matches email    │
│ Links to pending invite  │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ User completes onboarding│
│ status = active          │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ User sees new workspace  │
│ in workspace switcher    │
└──────────────────────────┘
```

---

## API Request Flow with RBAC

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Frontend sends API request:                     │
│                     POST /integrations/connect                      │
│                     Headers: Authorization: Bearer <JWT>            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 1. JWT Validation      │
              │    • Verify signature  │
              │    • Check expiry      │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ 2. get_current_user()  │
              │    • Extract sub (user)│
              │    • Load from DB      │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ 3. get_current_org()   │
              │    • Extract org_id    │
              │    • Load from DB      │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ 4. require_admin()     │
              │    • Check user.role   │
              │    • 403 if not admin  │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ 5. Route Handler       │
              │    • WHERE org_id=...  │
              │    • Execute logic     │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ 6. Response            │
              │    • 200 OK + data     │
              └────────────────────────┘
```

**If role check fails at step 4:**
```
              ┌────────────────────────┐
              │ require_admin()        │
              │ user.role = "member"   │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ HTTPException(403)     │
              │ "Admin access required"│
              └────────────────────────┘
```

---

## Workspace Limit Enforcement

```
User tries to create 4th workspace
         │
         ▼
┌──────────────────────────┐
│ Frontend checks:         │
│ memberships.length >= 3  │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ Toast error shown:       │
│ "Max 3 workspaces"       │
└──────────────────────────┘

         +

User bypasses frontend (direct API call)
         │
         ▼
┌──────────────────────────┐
│ Backend /onboarding:     │
│ len(memberships) >= 3    │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ HTTPException(400)       │
│ "Maximum limit reached"  │
└──────────────────────────┘
```

---

## Security Boundaries

```
┌───────────────────────────────────────────────────────────────────┐
│                      WORKSPACE A (Paytm)                          │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Chats      │  │ Integrations │  │    Team      │          │
│  │ org_id=AAA   │  │ org_id=AAA   │  │ org_id=AAA   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
                                │
                   ─────────────┴─────────────
                                │
                   ╔════════════════════════════╗
                   ║  SECURITY BOUNDARY        ║
                   ║  • JWT org_id validation  ║
                   ║  • Database org_id filter ║
                   ║  • No cross-org queries   ║
                   ╚════════════════════════════╝
                                │
                   ─────────────┬─────────────
                                │
┌───────────────────────────────────────────────────────────────────┐
│                  WORKSPACE B (Mahalaxmi)                          │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Chats      │  │ Integrations │  │    Team      │          │
│  │ org_id=BBB   │  │ org_id=BBB   │  │ org_id=BBB   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

**Impossible Scenarios (Blocked by Architecture):**
- ❌ User in Workspace A accessing Workspace B's chats
- ❌ Admin in Workspace A managing Workspace B's team
- ❌ Integration in Workspace A used by Workspace B
- ❌ Agent in Workspace A responding to Workspace B queries

---

## Summary

```
┌─────────────────────────────────────────────────────────────┐
│                 NIPUNA AI ARCHITECTURE                      │
│                                                             │
│  ✅ Complete workspace isolation via org_id                │
│  ✅ Role-based access control (Admin/Member/Viewer)        │
│  ✅ Secure team invitations (email + in-app)               │
│  ✅ Workspace switching with auto-context reload           │
│  ✅ 3-workspace limit enforcement                           │
│  ✅ Zero cross-workspace data leaks                         │
│                                                             │
│  PRODUCTION-READY FOR MULTI-TENANT SAAS ✨                │
└─────────────────────────────────────────────────────────────┘
```

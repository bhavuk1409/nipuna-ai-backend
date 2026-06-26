# Workspace System - Quick Reference Card

## For Developers

### Key Concept
**Every workspace = Completely independent company**
- Paytm workspace ≠ Mahalaxmi workspace
- Zero data overlap
- Different team members, different roles

---

## Role Permissions Matrix

| Feature | Admin | Member | Viewer |
|---------|-------|--------|--------|
| Use Ask Nipuna AI | ✅ Yes | ✅ Yes | ❌ No |
| Search Chats | ✅ Yes | ✅ Yes | ✅ Yes |
| View Team | ✅ Yes | ✅ Yes | ✅ Yes |
| Invite/Remove Team | ✅ Yes | ❌ No | ❌ No |
| Change Roles | ✅ Yes | ❌ No | ❌ No |
| View Integrations | ✅ Yes | ❌ No | ❌ No |
| Connect/Disconnect Integrations | ✅ Yes | ❌ No | ❌ No |
| Create/Edit Agents | ✅ Yes | ❌ No | ❌ No |
| Delete Workspace | ✅ Yes | ❌ No | ❌ No |

---

## Backend: How to Add a New Endpoint

### ✅ DO: Always scope by org_id
```python
@router.get("/my-endpoint")
async def my_endpoint(
    org: Organization = Depends(get_current_org),  # ✅ Required!
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MyModel).where(
            MyModel.org_id == org.id,  # ✅ Always filter by org!
        )
    )
    ...
```

### ❌ DON'T: Forget to filter by org_id
```python
# ❌ BAD - will return data from ALL workspaces!
result = await db.execute(select(MyModel))
```

### Enforce Role-Based Access
```python
from app.dependencies import require_admin

@router.post("/admin-only")
async def admin_only_endpoint(
    user: User = Depends(require_admin),  # ✅ Admin check
    ...
):
    ...
```

### Block Viewers from Write Operations
```python
def require_chat_permission(user: User = Depends(get_current_user)) -> User:
    if user.role == "viewer":
        raise HTTPException(status_code=403, detail="Viewers have read-only access")
    return user

@router.post("/send-message")
async def send_message(
    user: User = Depends(require_chat_permission),  # ✅ Viewer check
    ...
):
    ...
```

---

## Frontend: How to Add a New Feature

### Always Include org.id in Query Keys
```tsx
// ✅ CORRECT - query key includes org ID
const { data } = useQuery({
  queryKey: ["my-feature", organization?.id],
  queryFn: () => fetchApi("/my-endpoint"),
});
```

```tsx
// ❌ WRONG - missing org ID, stale data on workspace switch!
const { data } = useQuery({
  queryKey: ["my-feature"],
  queryFn: () => fetchApi("/my-endpoint"),
});
```

### Hide Features Based on Role
```tsx
const { data: userProfile } = useQuery({
  queryKey: ["current-user-profile", organization?.id],
  queryFn: () => fetchApi("/auth/me"),
});

const isAdmin = userProfile?.role === "admin";
const isViewer = userProfile?.role === "viewer";

return (
  <>
    {isAdmin && <AdminOnlyButton />}
    {!isViewer && <MemberButton />}
  </>
);
```

### Invalidate Queries on Mutation
```tsx
const inviteMutation = useMutation({
  mutationFn: (payload) => fetchApi("/team/invite", { ... }),
  onSuccess: () => {
    // ✅ Include org ID in invalidation
    queryClient.invalidateQueries({ 
      queryKey: ["team-members", organization?.id] 
    });
  },
});
```

---

## Common Patterns

### Pattern 1: Creating a Resource
```python
@router.post("/resources", response_model=ResourceResponse)
async def create_resource(
    body: ResourceCreate,
    org: Organization = Depends(get_current_org),
    user: User = Depends(require_admin),  # Admin-only
    db: AsyncSession = Depends(get_db),
):
    resource = Resource(
        org_id=org.id,  # ✅ Set org_id!
        name=body.name,
        created_by=user.id,
    )
    db.add(resource)
    await db.commit()
    return ResourceResponse.model_validate(resource)
```

### Pattern 2: Listing Resources
```python
@router.get("/resources", response_model=list[ResourceResponse])
async def list_resources(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Resource).where(
            Resource.org_id == org.id,  # ✅ Filter by org!
        ).order_by(Resource.created_at.desc())
    )
    resources = result.scalars().all()
    return [ResourceResponse.model_validate(r) for r in resources]
```

### Pattern 3: Updating a Resource
```python
@router.put("/resources/{resource_id}", response_model=ResourceResponse)
async def update_resource(
    resource_id: UUID,
    body: ResourceUpdate,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(require_admin),  # Admin-only
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.org_id == org.id,  # ✅ Verify org ownership!
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    # Update fields...
    await db.commit()
    return ResourceResponse.model_validate(resource)
```

---

## Testing Workspace Isolation

### Manual Test Script
1. Create 2 workspaces (Workspace A, Workspace B)
2. Create a resource in Workspace A
3. Switch to Workspace B
4. Try to access the resource → Should NOT appear
5. Switch back to Workspace A
6. Verify resource still exists

### Automated Test (Pytest)
```python
async def test_workspace_isolation(client, db):
    # Create 2 orgs
    org_a = Organization(clerk_org_id="org_a", name="Org A")
    org_b = Organization(clerk_org_id="org_b", name="Org B")
    db.add_all([org_a, org_b])
    await db.commit()
    
    # Create resource in org_a
    resource_a = Resource(org_id=org_a.id, name="Resource A")
    db.add(resource_a)
    await db.commit()
    
    # List resources for org_b
    result = await db.execute(
        select(Resource).where(Resource.org_id == org_b.id)
    )
    resources_b = result.scalars().all()
    
    # ✅ Assert no cross-workspace leak
    assert len(resources_b) == 0
    assert resource_a not in resources_b
```

---

## Debugging Workspace Issues

### Issue: Data appearing from wrong workspace
**Check:**
1. Is `org: Organization = Depends(get_current_org)` present?
2. Is query filtering by `org.id`?
3. Is frontend query key including `organization?.id`?

### Issue: Role not enforced correctly
**Check:**
1. Is `user: User = Depends(require_admin)` present?
2. Is frontend hiding UI based on `userProfile?.role`?
3. Is query key `["current-user-profile", org.id]` invalidated on workspace switch?

### Issue: Invitation not working
**Check:**
1. Is Clerk org ID correct in database?
2. Is email service configured (Resend API key)?
3. Is notification appearing in bell icon?
4. Check backend logs for Clerk API errors

---

## Useful Commands

### Run Backend
```bash
cd /Users/bhavukagrawal/nipuna-ai-backend/nipuna-backend
uvicorn app.main:app --reload --port 8000
```

### Run Database Migration
```bash
psql your_database_name < migrations/remove_conversation_unique_constraint.sql
```

### Check Current Workspaces
```sql
SELECT id, name, clerk_org_id FROM organizations;
```

### Check User Roles
```sql
SELECT u.email, u.role, o.name as workspace
FROM users u
JOIN organizations o ON u.org_id = o.id;
```

---

## Emergency Fixes

### User Stuck Without Workspace
```sql
-- Find user
SELECT * FROM users WHERE email = 'user@example.com';

-- Assign to workspace
UPDATE users 
SET org_id = 'workspace_uuid', role = 'admin', status = 'active'
WHERE email = 'user@example.com';
```

### Delete Workspace
```sql
-- WARNING: This deletes ALL data!
DELETE FROM organizations WHERE id = 'workspace_uuid';
```

---

## Need Help?

1. Read `WORKSPACE_ISOLATION_AUDIT.md` for technical details
2. Read `IMPLEMENTATION_SUMMARY.md` for high-level overview
3. Check backend logs for errors
4. Test with multiple browser sessions (different users)

**Remember:** Each workspace = Independent company. No shortcuts!

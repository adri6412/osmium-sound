---
name: release-versioning-rules
description: Critical rules for semantic versioning in release workflow
metadata:
  type: feedback
---

# 🚨 RELEASE VERSIONING RULES - CRITICAL

## RULE: Always increment by 0.0.1 (PATCH) at a time

**NEVER jump versions arbitrarily!**

### Correct Progression
```
v1.2.1 → v1.2.2 → v1.2.3 → v1.3.0 → v2.0.0
  patch   patch   patch   minor    major
```

### WRONG (DO NOT DO)
```
v1.2.1 → v2.5.0 ❌ INCORRECT
```

## Semantic Versioning Rules

### Patch (X.Y.Z)
- Increment when: Bug fixes only
- Example: v1.2.1 → v1.2.2
- Release type: Patch release

### Minor (X.Y.Z)
- Increment when: New features (backward compatible)
- Reset patch to 0: v1.2.x → v1.3.0
- Example: v1.2.9 → v1.3.0
- Release type: Minor release

### Major (X.Y.Z)
- Increment when: Breaking changes
- Reset minor and patch to 0: v1.x.x → v2.0.0
- Example: v1.99.99 → v2.0.0
- Release type: Major release

## Current Project State

**Last correct version**: v1.2.1  
**Next correct version**: v1.2.2 (PATCH for bug fixes/refactoring)

**ERROR**: Accidentally released as v2.5.0  
**FIX**: Need to correct to v1.2.2

## Release Process Checklist

- [ ] Identify release type: PATCH / MINOR / MAJOR
- [ ] Calculate new version correctly
- [ ] Update versionCode in build.gradle
- [ ] Update versionName in build.gradle
- [ ] Create commit: `chore(release): vX.Y.Z`
- [ ] Create tag: `git tag -a vX.Y.Z -m "..."`  (or `companion-vX.Y.Z`)
- [ ] Push tag: `git push origin vX.Y.Z`
- [ ] VERIFY version in git log before pushing

## For Companion App (Android)

**Separate versioning from desktop app:**
- Desktop app: v1.2.1, v1.2.2, v1.3.0, ...
- Companion app: Can have its own version (companion-v1.0.0, companion-v1.0.1, ...)
- **BUT**: Still follow semantic versioning rules!
- **NOT**: companion-v2.5.0 (wrong jump)
- **YES**: companion-v1.0.0 → companion-v1.0.1 → companion-v1.1.0

## Critical Reminders

🚨 **BEFORE PUSHING A RELEASE TAG**:
1. Double-check the version number
2. Verify it's the correct increment (patch/minor/major)
3. Confirm commit has the new version
4. Review git log one more time

⚠️ **If you make a mistake**:
1. Delete local tag: `git tag -d vX.Y.Z`
2. Delete remote tag: `git push origin :vX.Y.Z`
3. Fix the version number
4. Create new tag with correct version

## Why This Matters

- Semantic versioning tells users what changed
- Patch: safe to update (just fixes)
- Minor: new features, still backward compatible
- Major: breaking changes, careful update needed
- Jumping versions confuses version tracking and deployment systems

---

**CRITICAL**: Always increment by exactly 0.0.1 at a time!  
**TRUST BUT VERIFY**: Check version before pushing!

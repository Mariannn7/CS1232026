/* debver.c — розбір і порівняння версій Debian. ЛР 9, «Системне програмне забезпечення».
 * TODO 1 — debver_parse, TODO 2 — debver_part_cmp. */
#include "debver.h"

#include <ctype.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

static int fail(const char **err, const char *why)
{
    if (err)
        *err = why;
    return -1;
}

static int allowed(const char *s, const char *extra)
{
    for (; *s; s++)
        if (!isalnum((unsigned char)*s) && !strchr(extra, *s))
            return 0;
    return 1;
}

int debver_parse(const char *s, struct debver *v, const char **err)
{
    memset(v, 0, sizeof *v);
    if (s == NULL || *s == '\0')
        return fail(err, "empty version");

    for (const char *p = s; *p; p++) {
        if (isspace((unsigned char)*p))
            return fail(err, "whitespace in version");
    }

    const char *p = s;
    const char *colon = strchr(p, ':');
    if (colon != NULL) {
        if (colon == p)
            return fail(err, "empty epoch");
        unsigned long long ep = 0;
        for (const char *q = p; q < colon; q++) {
            if (!isdigit((unsigned char)*q))
                return fail(err, "non-digit in epoch");
            ep = ep * 10 + (unsigned)(*q - '0');
            if (ep > INT_MAX)
                return fail(err, "epoch overflow");
        }
        v->epoch = (unsigned)ep;
        p = colon + 1;
    }

    if (*p == '\0')
        return fail(err, "empty upstream version");

    const char *dash = strrchr(p, '-');
    const char *up_end;
    if (dash != NULL) {
        const char *rev = dash + 1;
        if (*rev == '\0')
            return fail(err, "empty revision");
        size_t rlen = strlen(rev);
        if (rlen >= DEBVER_MAX)
            return fail(err, "revision too long");
        memcpy(v->revision, rev, rlen + 1);
        if (!allowed(v->revision, ".+~"))
            return fail(err, "invalid char in revision");
        up_end = dash;
    } else {
        up_end = p + strlen(p);
    }

    size_t ulen = (size_t)(up_end - p);
    if (ulen == 0)
        return fail(err, "empty upstream version");
    if (ulen >= DEBVER_MAX)
        return fail(err, "upstream version too long");
    if (!isdigit((unsigned char)*p))
        return fail(err, "upstream must start with digit");

    memcpy(v->upstream, p, ulen);
    v->upstream[ulen] = '\0';

    const char *up_extra = ".+~";
    if (colon != NULL && dash != NULL)
        up_extra = ".+~-:";
    else if (colon != NULL)
        up_extra = ".+~:";
    else if (dash != NULL)
        up_extra = ".+~-";

    if (!allowed(v->upstream, up_extra))
        return fail(err, "invalid char in upstream");

    return 0;
}

/* Вага символу в нецифровій частині: ~ менша за все, навіть за кінець
 * рядка; кінець рядка — 0; літери — за кодом; решта — після літер. */
static int order(int c)
{
    if (c == '~')
        return -1;
    if (c == '\0' || isdigit(c))
        return 0;
    if (isalpha(c))
        return c;
    return c + 256;
}

int debver_part_cmp(const char *a, const char *b)
{
    while (*a || *b) {
        /* 1. Нецифровий шматок */
        while ((*a && !isdigit((unsigned char)*a)) ||
               (*b && !isdigit((unsigned char)*b))) {
            int ca = (*a && !isdigit((unsigned char)*a)) ? (unsigned char)*a : '\0';
            int cb = (*b && !isdigit((unsigned char)*b)) ? (unsigned char)*b : '\0';
            int oa = order(ca);
            int ob = order(cb);
            if (oa != ob)
                return oa < ob ? -1 : 1;
            if (ca)
                a++;
            if (cb)
                b++;
        }

        /* 2. Цифровий шматок (без переповнення числових типів) */
        while (*a == '0')
            a++;
        while (*b == '0')
            b++;

        const char *da = a;
        const char *db = b;
        while (isdigit((unsigned char)*a))
            a++;
        while (isdigit((unsigned char)*b))
            b++;

        size_t la = (size_t)(a - da);
        size_t lb = (size_t)(b - db);
        if (la != lb)
            return la < lb ? -1 : 1;

        int cmp = memcmp(da, db, la);
        if (cmp != 0)
            return cmp < 0 ? -1 : 1;
    }
    return 0;
}

int debver_cmp(const struct debver *a, const struct debver *b)
{
    if (a->epoch != b->epoch)
        return a->epoch < b->epoch ? -1 : 1;
    int r = debver_part_cmp(a->upstream, b->upstream);
    if (r)
        return r;
    return debver_part_cmp(a->revision, b->revision);
}

void debver_format(const struct debver *v, char *buf, unsigned long size)
{
    if (v->epoch)
        snprintf(buf, size, "%u:%s%s%s", v->epoch, v->upstream,
                 v->revision[0] ? "-" : "", v->revision);
    else
        snprintf(buf, size, "%s%s%s", v->upstream,
                 v->revision[0] ? "-" : "", v->revision);
}

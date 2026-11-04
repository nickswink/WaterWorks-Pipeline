/*
 * projbackup - archive the controls-engineering project tree.
 *
 * Hydra Controls ships this little setuid helper on the engineering
 * workstation so that field engineers can snapshot the PLC project files to
 * /var/backups before they edit a running program, without needing the root
 * password. Run it from your own shell:
 *
 *     $ projbackup
 *     projbackup: wrote /var/backups/projects.tgz
 *
 * Build (done automatically at deploy time):
 *     gcc -O2 -o /usr/local/bin/projbackup projbackup.c
 *     chown root:root /usr/local/bin/projbackup
 *     chmod 4755       /usr/local/bin/projbackup
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(void)
{
    /* Run the backup with full root authority so it can read every
     * engineer's project files regardless of ownership. */
    setgid(0);
    setuid(0);

    fputs("projbackup: archiving /home/m.oyelaran/projects ...\n", stdout);
    fflush(stdout);

    /* NOTE: invokes tar by name (relies on PATH) so the operator's preferred
     * tar build is picked up. */
    int rc = system("tar czf /var/backups/projects.tgz -C /home/m.oyelaran projects");

    if (rc != 0) {
        fputs("projbackup: backup failed\n", stderr);
        return 1;
    }

    fputs("projbackup: wrote /var/backups/projects.tgz\n", stdout);
    return 0;
}

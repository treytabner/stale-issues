"""
Stale issue bot for Github that closes
abandoned issues after a period of inactivity
"""

import argparse
import logging
import os
import sys

from datetime import datetime, timedelta

import yaml

from github import Github


DEFAULT_MARK_COMMENT = """
This issue has been automatically marked as stale because it has not
had recent activity. It will be closed if no further activity occurs.
"""


LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'
logging.basicConfig(format=LOG_FORMAT, datefmt='%c', stream=sys.stdout)
logger = logging.getLogger("__name__")
logger.setLevel(logging.DEBUG)


def get_args():
    """
    Setup command line arguments
    """

    parser = argparse.ArgumentParser(
        description='Handle stale Github issues')

    parser.add_argument('repo', help="Repo to manage")
    parser.add_argument('--base-url', default='api.github.com', help="Github API URL, defaults to api.github.com")
    parser.add_argument('--dry-run', action='store_const', const=True, help="Just show what would happen")

    return parser.parse_args()


class Stale():
    """
    Stale issue class
    """

    def __init__(self):
        """
        Setup stale issue config and connection to Github
        """
        self.args = get_args()
        logger.info("Connecting to %s", self.args.base_url.split('/')[0])
        self.github = Github(base_url='https://' + self.args.base_url, login_or_token=os.environ.get("GITHUB_TOKEN"))
        logger.info("Using repo %s", self.args.repo)
        self.repo = self.github.get_repo(self.args.repo)
        self.config = self.get_config()
        # self.config['limitPerRun'] = 1
        self.processed = 0

    def get_config(self):
        """
        Fetch stale.yml config from Github
        """
        logger.debug("Fetching .github/stale.yml content")
        content = self.repo.get_contents(".github/stale.yml")
        return yaml.safe_load(content.decoded_content.decode())

    def is_exempt(self, issue):
        """
        Check if issue is exempt from processing
        """

        # Check if the issue has any exmpted labels
        label_issues = [label.name for label in issue.labels]
        if set(self.config.get('exemptLabels')) & set(label_issues):
            logger.info("Issue %d is exempt due to labeling", issue.number)
            return True

        # Check if the issue has any assignees
        if issue.assignees and self.config.get('exemptAssignees', True):
            logger.info("Issue %s has assignees %s, skipping", issue.html_url,
                        ', '.join([user.email for user in issue.assignees]))
            return True

        # Check if the issue belongs to a milestone
        if issue.milestone and self.config.get('exemptMilestones', True):
            logger.info("Issue %s is in a milestone, skipping", issue.html_url)
            return True

        return False

    def process(self):
        """
        Fetch eligible issues and start processing
        """

        # Search for issues marked stale already first, then all other issues
        search_labels = [
            [self.config.get('staleLabel', 'stale')],
            self.config.get('onlyLabels', []),
        ]
        for labels in search_labels:
            issues = self.repo.get_issues(state='open', sort='updated-asc', labels=labels)
            for issue in issues:
                # Check to see if we have hit our per-run limit
                if (self.config.get('limitPerRun') and self.processed >= self.config.get('limitPerRun')):
                    logger.info("Processed enough issues already, ending for now.")
                    return

                # Check if issue is exempt from processing
                if self.is_exempt(issue):
                    continue

                # Process issue
                if self.process_issue(issue):
                    self.processed += 1

    def stale_path(self, issue):
        """
        Process already-stale issue
        """

        # Find out when the issue can be closed
        logger.info("Issue %d is stale!", issue.number)
        until_close = self.config.get('daysUntilClose')
        if until_close:
            close_date = datetime.utcnow() - timedelta(days=until_close)
            logger.debug("Close stale if older than: %s", close_date.isoformat())
        else:
            return False

        # Check to see if there were any new comments to keep the issue open
        last_comment = issue.get_comments().reversed[0]
        if last_comment.body == self.config.get('markComment', DEFAULT_MARK_COMMENT):
            # No new comment, so checking to see if we can close the issue
            if last_comment.updated_at < close_date:
                # Close issue
                if not self.args.dry_run:
                    if self.config.get('closeComment'):
                        logger.info("Adding close comment to issue %d", issue.number)
                        issue.create_comment(self.config.get('closeComment'))
                    logger.info("Closing issue %d", issue.number)
                    issue.edit(state='closed')
                return True

            logger.info("Issue %d is not stale enough", issue.number)
            logger.debug("Last comment at: %s", last_comment.updated_at.isoformat())
            logger.debug("Would be able to close in %s hours", issue.updated_at - close_date)

        else:
            # New comment found on issue so remove the stale label
            logger.info("New comment found, on issue %d, " "removing stale label", issue.number)
            if not self.args.dry_run:
                logger.info("Removing stale label from issue %d", issue.number)
                issue.remove_from_labels(self.config.get('staleLabel', 'stale'))
                if self.config.get('unmarkComment'):
                    issue.create_comment(self.config.get('unmarkComment'))
            return True

        return False

    def process_issue(self, issue):
        """
        Process a specific issue by checking for activity and staleness
        """
        logger.info("Processing %s (%s)", issue.html_url, issue.title)
        logger.debug("Current time: %s", datetime.utcnow().isoformat())

        # Find out when the issue will go stale
        until_stale = self.config.get('daysUntilStale', 60)
        stale_date = datetime.utcnow() - timedelta(days=until_stale)
        logger.debug("Stale if olders than: %s", stale_date.isoformat())

        # If issue is already marked stale, possibly close or unmark stale
        label_issues = [label.name for label in issue.labels]
        if self.config.get('staleLabel', 'stale') in label_issues:
            return self.stale_path(issue)

        # Else check issue to see if it should be marked stale
        logger.debug("Last update at %s", issue.updated_at.isoformat())
        logger.debug("Would be stale in %s hours", issue.updated_at - stale_date)
        if issue.updated_at < stale_date:
            logger.info("Marking issue %d stale", issue.number)
            if not self.args.dry_run:
                issue.add_to_labels(self.config.get('staleLabel', 'stale'))
                issue.create_comment(self.config.get('markComment', DEFAULT_MARK_COMMENT))
            return True

        # If we get here all remaining issues are not ready to mark stale, so end early
        self.processed = self.config.get('limitPerRun')
        return False


def main():
    """
    Process stale issues
    """
    Stale().process()


if __name__ == "__main__":
    main()

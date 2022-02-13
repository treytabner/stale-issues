"""
Stale issue bot for Github that closes
abandoned issues after a period of inactivity
"""

import argparse
import logging
import os

from datetime import datetime, timedelta

import yaml

from github import Github


DEFAULT_MARK_COMMENT = """
This issue has been automatically marked as stale because it has not
had recent activity. It will be closed if no further activity occurs.
"""


LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'
logging.basicConfig(format=LOG_FORMAT, datefmt='%c')
logger = logging.getLogger("__name__")
logger.setLevel(logging.INFO)


def get_args():
    """
    Setup command line arguments
    """

    parser = argparse.ArgumentParser(
        description='Handle stale Github issues')

    parser.add_argument('repo', help="Repo to manage")
    parser.add_argument('--base-url', default='api.github.com',
                        help="Github API URL, defaults to api.github.com")
    parser.add_argument('--dry-run', action='store_const', const=True,
                        help="Just show what would happen")

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
        self.github = Github(base_url='https://' + self.args.base_url,
                             login_or_token=os.environ.get("GITHUB_TOKEN"))
        logger.info("Using repo %s", self.args.repo)
        self.repo = self.github.get_repo(self.args.repo)
        self.config = self.get_config()

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
        label_issues = [label.name for label in issue.labels]
        if set(self.config.get('exemptLabels')) & set(label_issues):
            logger.info("Issue %d is exempt due to labeling", issue.number)
            return True

        if issue.assignees and self.config.get('exemptAssignees', True):
            logger.info("Issue %d has assignees, skipping", issue.number)
            return True

        if issue.milestone and self.config.get('exemptMilestones', True):
            logger.info("Issue %d is in a milestone, skipping", issue.number)
            return True

        return False

    def process(self):
        """
        Fetch eligible issues and start processing
        """
        until_stale = self.config.get('daysUntilStale')
        until_close = self.config.get('daysUntilClose')

        if not all([until_stale, until_close]):
            logger.error(
                "Specify both daysUntilStale and daysUntilClose in stale.yaml")
            return

        processed = 0
        issues = self.repo.get_issues(state='open', sort='updated-asc',
                                      labels=self.config.get('onlyLabels', []))
        for issue in issues:
            if (self.config.get('limitPerRun') and
                    processed >= self.config.get('limitPerRun')):
                logger.warning("Processed %d issues already, ending.",
                               processed)
                return

            if self.is_exempt(issue):
                continue

            if self.process_issue(issue):
                processed += 1

    def stale_path(self, issue):
        """
        Process already-stale issue
        """
        logger.info("Issue %d is stale!", issue.number)
        until_close = self.config.get('daysUntilClose')
        close_date = datetime.utcnow() - timedelta(days=until_close)
        logger.debug("Close stale if older than: %s", close_date.isoformat())

        last_comment = issue.get_comments().reversed[0]
        if last_comment.body == self.config.get('markComment',
                                                DEFAULT_MARK_COMMENT):
            # check date and possibly close
            if last_comment.updated_at < close_date:
                if self.config.get('closeComment'):
                    logger.info("Adding close comment to issue %d",
                                issue.number)
                    if not self.args.dry_run:
                        issue.create_comment(
                            self.config.get('closeComment'))
                logger.info("Closing issue %d", issue.number)
                if self.config.get('closeComment'):
                    issue.create_comment(self.config.get('closeComment'))
                if not self.args.dry_run:
                    issue.edit(state='closed')
                return True

            logger.info("Issue %d is not stale enough", issue.number)
            logger.debug("Last comment at: %s",
                         last_comment.updated_at.isoformat())
            logger.debug("Would be able to close in %s hours",
                         issue.updated_at - close_date)

        else:
            logger.info("New comment found, on issue %d, "
                        "removing stale label", issue.number)
            if not self.args.dry_run:
                logger.info("Removing stale label from issue %d",
                            issue.number)
                issue.remove_from_labels(
                    self.config.get('staleLabel', 'stale'))
                if self.config.get('unmarkComment'):
                    issue.create_comment(self.config.get('unmarkComment'))
            return True

        return False

    def process_issue(self, issue):
        """
        Process a specific issue by checking for activity and staleness
        """
        logger.info("Processing %s (%s)", issue.number, issue.title)
        logger.debug("Current time: %s", datetime.utcnow().isoformat())

        until_stale = self.config.get('daysUntilStale')
        stale_date = datetime.utcnow() - timedelta(days=until_stale)
        logger.debug("Stale if olders than: %s", stale_date.isoformat())

        label_issues = [label.name for label in issue.labels]
        if self.config.get('staleLabel', 'stale') in label_issues:
            return self.stale_path(issue)

        logger.debug("Last update at %s", issue.updated_at.isoformat())
        logger.debug("Would be stale in %s hours",
                     issue.updated_at - stale_date)
        if issue.updated_at < stale_date:
            logger.info("Marking issue %d stale", issue.number)
            if not self.args.dry_run:
                issue.add_to_labels(self.config.get('staleLabel', 'stale'))
                issue.create_comment(self.config.get('markComment',
                                     DEFAULT_MARK_COMMENT))
            return True

        logger.info("Issue %d has recent activity, skipping", issue.number)
        return False


def main():
    """
    Process stale issues
    """
    Stale().process()


if __name__ == "__main__":
    main()

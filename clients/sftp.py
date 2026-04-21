"""Generic SFTP client wrapper using Paramiko."""
import io
import logging
from pathlib import PurePosixPath

import paramiko

logger = logging.getLogger(__name__)


class SFTPClient:
    """Simple SFTP client for uploading/downloading files."""

    def __init__(self, host: str, username: str, password: str, port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self._transport: paramiko.Transport | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def connect(self):
        """Open SFTP connection."""
        self._transport = paramiko.Transport((self.host, self.port))
        self._transport.connect(username=self.username, password=self.password)
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        logger.info("SFTP: connected to %s:%d", self.host, self.port)

    def close(self):
        """Close SFTP connection."""
        if self._sftp:
            self._sftp.close()
        if self._transport:
            self._transport.close()
        logger.info("SFTP: disconnected from %s", self.host)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def upload_string(self, content: str, remote_path: str) -> None:
        """Upload a string as a file to the remote path."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        buf = io.BytesIO(content.encode("utf-8"))
        self._sftp.putfo(buf, remote_path)
        logger.info("SFTP: uploaded %d bytes to %s", len(content), remote_path)

    def upload_file(self, local_path: str, remote_path: str) -> None:
        """Upload a local file to the remote path."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        self._sftp.put(local_path, remote_path)
        logger.info("SFTP: uploaded %s to %s", local_path, remote_path)

    def download_string(self, remote_path: str) -> str:
        """Download a remote file and return its content as a string."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        buf = io.BytesIO()
        self._sftp.getfo(remote_path, buf)
        content = buf.getvalue().decode("utf-8")
        logger.info("SFTP: downloaded %d bytes from %s", len(content), remote_path)
        return content

    def list_dir(self, remote_path: str) -> list[str]:
        """List files in a remote directory."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        return self._sftp.listdir(remote_path)

    def check_health(self) -> bool:
        """Test SFTP connectivity."""
        try:
            self.connect()
            self._sftp.listdir(".")
            self.close()
            return True
        except Exception as e:
            logger.error("SFTP health check failed: %s", e)
            return False

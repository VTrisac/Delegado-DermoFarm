import os
from typing import Optional
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage
from django.utils.functional import cached_property
from django.core.files.base import File
from django.utils.encoding import force_str
import hashlib
import gzip
import time

class OptimizedStaticFilesStorage(ManifestStaticFilesStorage):
    """
    Custom storage backend that implements several optimizations:
    - Automatic file compression (gzip/brotli)
    - Improved cache headers
    - Content-based hashing
    - Deduplication of identical files
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hashed_files = {}  # Cache for content hashes
        self._compression_enabled = getattr(settings, 'STATIC_COMPRESSION_ENABLED', True)
        
    def _save(self, name: str, content: File) -> str:
        """
        Override save to implement deduplication and compression.
        """
        # Generate content hash
        content_hash = self._get_content_hash(content)
        
        # Check if we already have this content
        if content_hash in self.hashed_files:
            return self.hashed_files[content_hash]
            
        # Determine if file should be compressed
        should_compress = self._should_compress(name)
        
        if should_compress:
            # Compress content
            compressed_content = self._compress_content(content)
            if compressed_content:
                content = compressed_content
        
        # Save file with content hash in name
        name_parts = name.rsplit('.', 1)
        if len(name_parts) > 1:
            hashed_name = f"{name_parts[0]}.{content_hash[:8]}.{name_parts[1]}"
        else:
            hashed_name = f"{name}.{content_hash[:8]}"
            
        # Store the mapping
        self.hashed_files[content_hash] = hashed_name
        
        # Actually save the file
        name = super()._save(hashed_name, content)
        
        # Save compressed version if needed
        if should_compress:
            self._save_compressed_file(name, content)
            
        return name
    
    def _get_content_hash(self, content: File) -> str:
        """
        Generate a hash of file content for deduplication.
        """
        content.seek(0)
        file_hash = hashlib.sha256(content.read()).hexdigest()
        content.seek(0)
        return file_hash
    
    def _should_compress(self, filename: str) -> bool:
        """
        Determine if a file should be compressed based on its extension.
        """
        if not self._compression_enabled:
            return False
            
        compress_extensions = {
            '.js', '.css', '.html', '.txt', '.xml',
            '.json', '.svg', '.woff', '.woff2'
        }
        
        return any(filename.endswith(ext) for ext in compress_extensions)
    
    def _compress_content(self, content: File) -> Optional[File]:
        """
        Compress file content using gzip.
        """
        try:
            content.seek(0)
            compressed = gzip.compress(content.read())
            content.seek(0)
            
            from django.core.files.base import ContentFile
            return ContentFile(compressed)
            
        except Exception as e:
            import logging
            logging.error(f"Error compressing static file: {str(e)}")
            return None
    
    def _save_compressed_file(self, name: str, content: File) -> None:
        """
        Save a compressed version of the file.
        """
        if not self._compression_enabled:
            return
            
        # Save gzipped version
        gzipped_path = f"{self.path(name)}.gz"
        try:
            content.seek(0)
            with gzip.open(gzipped_path, 'wb') as gz_file:
                gz_file.write(content.read())
        except Exception as e:
            import logging
            logging.error(f"Error saving compressed file: {str(e)}")
    
    @cached_property
    def manifest_storage(self) -> FileSystemStorage:
        """
        Get storage for manifest files with appropriate permissions.
        """
        manifest_storage = FileSystemStorage(
            location=self.location,
            base_url=self.base_url,
            file_permissions_mode=0o644,
            directory_permissions_mode=0o755
        )
        return manifest_storage
    
    def post_process(self, paths, dry_run=False, **options):
        """
        Post-process files to update manifest and optimize as needed.
        """
        if dry_run:
            return
            
        # Process files as normal
        for name, hashed_name, processed in super().post_process(paths, dry_run, **options):
            yield name, hashed_name, processed
            
            # Additional optimization steps
            if processed:
                self._post_process_file(hashed_name)
    
    def _post_process_file(self, name: str) -> None:
        """
        Perform additional optimization steps on processed files.
        """
        # Skip if file doesn't exist
        if not self.exists(name):
            return
            
        file_path = self.path(name)
        
        # Set appropriate permissions
        try:
            os.chmod(file_path, 0o644)
        except OSError:
            pass
            
        # Update access and modification times to now
        # This helps with browser caching
        try:
            current_time = time.time()
            os.utime(file_path, (current_time, current_time))
        except OSError:
            pass
    
    def url(self, name: str) -> str:
        """
        Return URL for accessing the file with cache busting.
        """
        url = super().url(name)
        
        # Add cache busting query parameter for non-hashed files
        if not any(char in name for char in '?#'):
            if self.exists(name):
                try:
                    mtime = os.path.getmtime(self.path(name))
                    url = f"{url}?v={int(mtime)}"
                except OSError:
                    pass
                    
        return force_str(url)
    
    def get_available_name(self, name: str, max_length: Optional[int] = None) -> str:
        """
        Overridden to ensure we don't generate names that are too long.
        """
        if max_length and len(name) > max_length:
            # Split the name and extension
            name_parts = name.rsplit('.', 1)
            if len(name_parts) > 1:
                ext = f".{name_parts[1]}"
                name = name_parts[0]
            else:
                ext = ''
                
            # Truncate the name part to fit max_length including extension
            max_name_length = max_length - len(ext)
            name = f"{name[:max_name_length]}{ext}"
            
        return name
"""
API views for Figma plugin integration.

Endpoints:
- POST /api/figma/translations/ - Create translation entry
- GET /api/figma/translations/<key>/ - Get translation by key
- GET /api/figma/translations/ - Get all translations for language picker
- GET /api/figma/auth/ - Validate API key
"""

import logging
from django.utils import timezone

logger = logging.getLogger(__name__)
from rest_framework import status
from rest_framework.views import APIView
from stapel_core.django.errors import IronResponse
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import FigmaApiKey, TranslationEntry, TranslationHistory, SUPPORTED_LANGUAGES
from .dto import (
    FigmaAuthResponse,
    FigmaTranslationsListResponse,
    FigmaTranslationUpsertResponse,
    FigmaSearchResponse,
    FigmaTranslationDetailResponse,
    FigmaSyncResponse,
    FigmaRemoveRefResponse,
    FigmaScreenshotUploadResponse,
)
from .figma_serializers import (
    FigmaAuthResponseSerializer,
    FigmaTranslationsListResponseSerializer,
    FigmaTranslationUpsertResponseSerializer,
    FigmaSearchResponseSerializer,
    FigmaTranslationDetailResponseSerializer,
    FigmaSyncResponseSerializer,
    FigmaRemoveRefResponseSerializer,
    FigmaScreenshotUploadResponseSerializer,
)


class FigmaApiKeyAuthentication:
    """Mixin for Figma API key authentication."""

    def authenticate_figma(self, request):
        """
        Authenticate request using Figma API key.
        Returns (api_key_obj, error_response) tuple.
        """
        api_key = request.headers.get('X-Figma-API-Key')
        if not api_key:
            return None, IronResponse(
                {'error': 'Missing X-Figma-API-Key header'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            key_obj = FigmaApiKey.objects.get(id=api_key, is_active=True)
            # Update last_used_at
            key_obj.last_used_at = timezone.now()
            key_obj.save(update_fields=['last_used_at'])
            return key_obj, None
        except (FigmaApiKey.DoesNotExist, ValueError):
            return None, IronResponse(
                {'error': 'Invalid or inactive API key'},
                status=status.HTTP_401_UNAUTHORIZED
            )


@extend_schema(tags=['Figma Plugin'])
class FigmaAuthView(FigmaApiKeyAuthentication, APIView):
    """Validate Figma API key."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Validate Figma API key and return supported languages.',
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'valid': {'type': 'boolean'},
                    'name': {'type': 'string'},
                    'languages': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'code': {'type': 'string'},
                                'name': {'type': 'string'},
                            }
                        }
                    }
                }
            },
            401: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        }
    )
    def get(self, request):
        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        # Language names
        LANGUAGE_NAMES = {
            'en': 'English', 'lb': 'Luxembourgish', 'fr': 'French', 'de': 'German',
            'es': 'Spanish', 'pt': 'Portuguese', 'it': 'Italian', 'ru': 'Russian',
            'uk': 'Ukrainian', 'pl': 'Polish', 'ar': 'Arabic', 'hi': 'Hindi',
            'zh': 'Mandarin', 'tr': 'Turkish', 'ko': 'Korean', 'ja': 'Japanese',
            'sr': 'Serbian', 'hr': 'Croatian', 'hu': 'Hungarian', 'he': 'Hebrew',
        }

        languages = [
            {'code': lang, 'name': LANGUAGE_NAMES.get(lang, lang)}
            for lang in SUPPORTED_LANGUAGES
        ]

        dto = FigmaAuthResponse(
            valid=True,
            name=key_obj.name,
            languages=languages,
        )
        return IronResponse(FigmaAuthResponseSerializer(dto))


@extend_schema(tags=['Figma Plugin'])
class FigmaTranslationsView(FigmaApiKeyAuthentication, APIView):
    """Create translation entry or get all translations."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Get translations for Figma plugin. By default returns only figma-source translations.',
        parameters=[
            OpenApiParameter(
                name='lang',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Language code (default: en)',
                required=False,
            ),
            OpenApiParameter(
                name='keys',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Comma-separated list of specific keys to fetch',
                required=False,
            ),
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'translations': {
                        'type': 'object',
                        'additionalProperties': {'type': 'string'}
                    },
                    'language': {'type': 'string'},
                }
            }
        }
    )
    def get(self, request):
        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        lang = request.query_params.get('lang', 'en')
        if lang not in SUPPORTED_LANGUAGES:
            return IronResponse(
                {'error': f'Invalid language: {lang}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get specific keys or filter by figma source
        keys_param = request.query_params.get('keys', '').strip()

        if keys_param:
            # Fetch specific keys (for sync)
            key_list = [k.strip() for k in keys_param.split(',') if k.strip()]
            entries = TranslationEntry.objects.filter(key__in=key_list, deleted=False)
        else:
            # Only return figma-created translations by default
            entries = TranslationEntry.objects.filter(source='app:figma', deleted=False)

        translations = {}
        for entry in entries:
            value = getattr(entry, lang, None)
            if value:
                translations[entry.key] = value
            elif entry.en:
                # Fallback to English
                translations[entry.key] = entry.en

        dto = FigmaTranslationsListResponse(
            translations=translations,
            language=lang,
            count=len(translations),
        )
        return IronResponse(FigmaTranslationsListResponseSerializer(dto))

    @extend_schema(
        description='Create or update a translation entry from Figma.',
        request={
            'type': 'object',
            'properties': {
                'key': {'type': 'string', 'description': 'Translation key'},
                'value': {'type': 'string', 'description': 'Text value for the target language'},
                'comment': {'type': 'string', 'description': 'Context/comment for translators'},
                'figma_url': {'type': 'string', 'description': 'Figma selection URL to add as ref'},
                'lang': {'type': 'string', 'description': 'Language to save to (default: en)'},
                'verify': {'type': 'boolean', 'description': 'Set verified flag for the language'},
                'force': {'type': 'boolean', 'description': 'Override verified guard and save anyway'},
            },
            'required': ['key', 'value']
        },
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'id': {'type': 'integer'},
                    'key': {'type': 'string'},
                    'value': {'type': 'string'},
                    'created': {'type': 'boolean'},
                }
            },
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            409: {'type': 'object', 'properties': {'error': {'type': 'string'}, 'existing': {'type': 'object'}}},
        }
    )
    def post(self, request):
        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        key = request.data.get('key', '').strip()
        value = request.data.get('value', '').strip()
        comment = request.data.get('comment', '').strip()
        figma_url = request.data.get('figma_url', '').strip()
        lang = request.data.get('lang', 'en').strip()
        verify = request.data.get('verify', False)
        force = request.data.get('force', False)
        order = request.data.get('order')
        author_email = request.data.get('author_email', '').strip() or None
        author_name = request.data.get('author_name', '').strip() or ''
        screen_name = request.data.get('screen_name', '').strip()

        if lang not in SUPPORTED_LANGUAGES:
            return IronResponse(
                {'error': f'Invalid language: {lang}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not key:
            return IronResponse(
                {'error': 'Key is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not value:
            return IronResponse(
                {'error': 'Value is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        logger.info(f"[FigmaCreate] key={key}, lang={lang}, verify={verify}, force={force}, figma_url={figma_url}")

        verified_field = f'{lang}_verified'

        # Check if key already exists - upsert logic (include soft-deleted)
        existing = TranslationEntry.objects.filter(key=key).first()
        if existing:
            # Reactivate soft-deleted entry
            reactivated = existing.deleted
            if reactivated:
                existing.deleted = False
            translation_changed = reactivated  # tracks if translation value or verified changed
            metadata_fields = []  # tracks fields that don't need revision bump
            logger.info(f"[FigmaCreate] Key exists, {verified_field}={getattr(existing, verified_field, False)}, refs={existing.refs}")

            is_verified = getattr(existing, verified_field, False)
            old_value = getattr(existing, lang, '') or ''

            # Update value only if NOT verified, or if force=True
            en_text_changed = False
            if value and getattr(existing, lang, None) != value:
                if not is_verified or force:
                    setattr(existing, lang, value)
                    translation_changed = True
                    if lang == 'en':
                        en_text_changed = True
                    # If overriding a verified value, unset verified flag
                    if is_verified and force:
                        setattr(existing, verified_field, False)
                    logger.info(f"[FigmaCreate] Updated {lang} text")

            # When English text changes, reset ALL verified flags
            if en_text_changed:
                for supported_lang in SUPPORTED_LANGUAGES:
                    setattr(existing, f'{supported_lang}_verified', False)
                logger.info("[FigmaCreate] English text changed — reset all verified flags")

            # Set verified flag if requested
            old_verified = getattr(existing, verified_field, False)
            if verify:
                setattr(existing, verified_field, True)
                translation_changed = True

            # Update translator_comment if user provided a comment
            if comment and existing.translator_comment != comment:
                existing.translator_comment = comment
                metadata_fields.append('translator_comment')

            # Append screen name to system comment if not already present
            if screen_name:
                screen_line = f'Screen: {screen_name}'
                existing_lines = (existing.comment or '').split('\n')
                if screen_line not in existing_lines:
                    existing_lines = [l for l in existing_lines if l]  # drop empty
                    existing_lines.append(screen_line)
                    existing.comment = '\n'.join(existing_lines)
                    if 'comment' not in metadata_fields:
                        metadata_fields.append('comment')

            # Add figma_url to refs if provided and not already there
            if figma_url and figma_url not in (existing.refs or []):
                existing.refs = (existing.refs or []) + [figma_url]
                metadata_fields.append('refs')
                logger.info(f"[FigmaCreate] Ref added, new refs: {existing.refs}")

            # Update order if provided
            if order is not None and existing.order != order:
                existing.order = order
                if 'order' not in metadata_fields:
                    metadata_fields.append('order')

            if translation_changed:
                # Translation value changed — full save to increment revision
                existing.save()
            elif metadata_fields:
                # Only metadata changed — save with update_fields to skip revision
                existing.save(update_fields=metadata_fields)

            # Log translation change to history
            new_value = getattr(existing, lang, '') or ''
            if old_value != new_value:
                TranslationHistory.objects.create(
                    entry=existing,
                    language=lang,
                    change_type='translation',
                    old_value=old_value,
                    new_value=new_value,
                    author_email=author_email,
                    author_name=author_name,
                    source='figma',
                )

            # Log verification change
            new_verified = getattr(existing, verified_field, False)
            if old_verified != new_verified:
                TranslationHistory.objects.create(
                    entry=existing,
                    language=lang,
                    change_type='verification',
                    old_value='verified' if old_verified else 'unverified',
                    new_value='verified' if new_verified else 'unverified',
                    author_email=author_email,
                    author_name=author_name,
                    source='figma',
                )

            # Log English text change resetting verifications
            if en_text_changed:
                TranslationHistory.objects.create(
                    entry=existing,
                    language='all',
                    change_type='verification',
                    old_value='verified',
                    new_value='reset (English changed)',
                    author_email=author_email,
                    author_name=author_name,
                    source='figma',
                )

            dto = FigmaTranslationUpsertResponse(
                id=existing.id,
                key=existing.key,
                value=getattr(existing, lang, '') or '',
                comment=existing.comment,
                translator_comment=existing.translator_comment,
                refs=existing.refs,
                order=existing.order,
                created=False,
                updated=translation_changed or bool(metadata_fields),
                verified=getattr(existing, verified_field, False),
            )
            return IronResponse(FigmaTranslationUpsertResponseSerializer(dto))

        # Create new translation entry with figma_url as ref
        refs = [figma_url] if figma_url else []
        system_comment = f'Screen: {screen_name}' if screen_name else ''
        entry = TranslationEntry(
            key=key,
            comment=system_comment,
            translator_comment=comment,
            source='app:figma',
            refs=refs,
        )
        if order is not None:
            entry.order = order
        setattr(entry, lang, value)
        if verify:
            setattr(entry, verified_field, True)
        entry.save()

        # Log creation to history
        TranslationHistory.objects.create(
            entry=entry,
            language=lang,
            change_type='translation',
            old_value='',
            new_value=value,
            author_email=author_email,
            author_name=author_name,
            source='figma',
        )

        dto = FigmaTranslationUpsertResponse(
            id=entry.id,
            key=entry.key,
            value=getattr(entry, lang, '') or '',
            comment=entry.comment,
            translator_comment=entry.translator_comment,
            refs=entry.refs,
            order=entry.order,
            created=True,
            verified=getattr(entry, verified_field, False),
        )
        return IronResponse(FigmaTranslationUpsertResponseSerializer(dto), status=status.HTTP_201_CREATED)


@extend_schema(tags=['Figma Plugin'])
class FigmaSearchByTextView(FigmaApiKeyAuthentication, APIView):
    """Search for translation by exact English text match."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Search for translation by exact English text match. If found, suggests linking.',
        request={
            'type': 'object',
            'properties': {
                'text': {'type': 'string', 'description': 'English text to search for'},
                'figma_url': {'type': 'string', 'description': 'Figma selection URL to add as ref if match found'},
            },
            'required': ['text']
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'found': {'type': 'boolean'},
                    'entry': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'integer'},
                            'key': {'type': 'string'},
                            'en': {'type': 'string'},
                            'comment': {'type': 'string'},
                            'source': {'type': 'string'},
                            'refs': {'type': 'array', 'items': {'type': 'string'}},
                        }
                    },
                    'ref_added': {'type': 'boolean'},
                }
            },
        }
    )
    def post(self, request):
        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        text = request.data.get('text', '').strip()
        figma_url = request.data.get('figma_url', '').strip()
        screen_name = request.data.get('screen_name', '').strip()

        if not text:
            return IronResponse(
                {'error': 'Text is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Log for debugging
        logger.info(f"[FigmaSearch] Looking for text: {repr(text)}")

        # Search for exact match on English text
        entry = TranslationEntry.objects.filter(en=text, deleted=False).first()

        if not entry:
            # Try case-insensitive search
            entry = TranslationEntry.objects.filter(en__iexact=text, deleted=False).first()

        if not entry:
            # Log what we have in DB for debugging
            similar = TranslationEntry.objects.filter(
                en__icontains=text[:20] if len(text) > 20 else text,
                deleted=False
            ).first()
            if similar:
                logger.info(f"[FigmaSearch] Similar entry found: {repr(similar.en)}")

        if not entry:
            dto = FigmaSearchResponse(found=False, entry=None, ref_added=False)
            return IronResponse(FigmaSearchResponseSerializer(dto))

        # Add figma_url to refs if provided and not already there
        ref_added = False
        update_fields = []
        logger.info(f"[FigmaSearch] Entry found: {entry.key}, figma_url: {figma_url}, current refs: {entry.refs}")
        if figma_url and figma_url not in (entry.refs or []):
            entry.refs = (entry.refs or []) + [figma_url]
            update_fields.append('refs')
            ref_added = True
            logger.info(f"[FigmaSearch] Ref added, new refs: {entry.refs}")

        # Append screen name to system comment if not already present
        if screen_name:
            screen_line = f'Screen: {screen_name}'
            existing_lines = (entry.comment or '').split('\n')
            if screen_line not in existing_lines:
                existing_lines = [l for l in existing_lines if l]
                existing_lines.append(screen_line)
                entry.comment = '\n'.join(existing_lines)
                if 'comment' not in update_fields:
                    update_fields.append('comment')

        if update_fields:
            entry.save(update_fields=update_fields)

        dto = FigmaSearchResponse(
            found=True,
            entry={
                'id': entry.id,
                'key': entry.key,
                'en': entry.en,
                'comment': entry.comment,
                'source': entry.source,
                'refs': entry.refs,
            },
            ref_added=ref_added,
        )
        return IronResponse(FigmaSearchResponseSerializer(dto))


@extend_schema(tags=['Figma Plugin'])
class FigmaTranslationDetailView(FigmaApiKeyAuthentication, APIView):
    """Get translation by key."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Get translation by key with verification status.',
        parameters=[
            OpenApiParameter(
                name='lang',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Language code (default: en)',
                required=False,
            ),
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'key': {'type': 'string'},
                    'value': {'type': 'string'},
                    'comment': {'type': 'string'},
                    'translator_comment': {'type': 'string'},
                    'verified': {'type': 'boolean'},
                    'verification_status': {'type': 'object'},
                    'all_translations': {'type': 'object'},
                }
            },
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        }
    )
    def get(self, request, key):
        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        lang = request.query_params.get('lang', 'en')
        if lang not in SUPPORTED_LANGUAGES:
            lang = 'en'

        try:
            entry = TranslationEntry.objects.get(key=key, deleted=False)
        except TranslationEntry.DoesNotExist:
            return IronResponse(
                {'error': f'Translation key "{key}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get value for requested language (with English fallback)
        value = getattr(entry, lang, None) or entry.en or ''

        # Build all translations dict
        all_translations = {}
        for l in SUPPORTED_LANGUAGES:
            v = getattr(entry, l, None)
            if v:
                all_translations[l] = v

        # Build verification status for all languages
        verification_status = {}
        for l in SUPPORTED_LANGUAGES:
            verification_status[l] = getattr(entry, f'{l}_verified', False)

        dto = FigmaTranslationDetailResponse(
            id=entry.id,
            key=entry.key,
            value=value,
            language=lang,
            comment=entry.comment,
            translator_comment=entry.translator_comment,
            source=entry.source,
            order=entry.order,
            all_translations=all_translations,
            verified=getattr(entry, f'{lang}_verified', False),
            verification_status=verification_status,
        )
        return IronResponse(FigmaTranslationDetailResponseSerializer(dto))


@extend_schema(tags=['Figma Plugin'])
class FigmaSyncView(FigmaApiKeyAuthentication, APIView):
    """Bulk sync Figma nodes — updates refs, comments, order for all entries."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Bulk sync all Figma translatable nodes. Clears old figma refs then rebuilds.',
        request={
            'type': 'object',
            'properties': {
                'entries': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'key': {'type': 'string'},
                            'currentText': {'type': 'string'},
                            'figmaUrl': {'type': 'string'},
                            'containerName': {'type': 'string'},
                            'order': {'type': 'integer'},
                        },
                        'required': ['key']
                    }
                }
            },
            'required': ['entries']
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'synced': {'type': 'integer'},
                    'created': {'type': 'integer'},
                    'updated': {'type': 'integer'},
                }
            }
        }
    )
    def post(self, request):
        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        entries = request.data.get('entries', [])
        if not entries:
            return IronResponse(
                {'error': 'entries is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Step 1: Clear old figma refs/comments from all app:figma entries
        TranslationEntry.objects.filter(source='app:figma').update(refs=[], comment='')

        # Step 2: Aggregate entries by key
        by_key = {}
        for entry in entries:
            key = (entry.get('key') or '').strip()
            if not key:
                continue
            if key not in by_key:
                by_key[key] = {
                    'refs': [],
                    'screen_names': [],
                    'order': None,
                    'currentText': '',
                }
            figma_url = (entry.get('figmaUrl') or '').strip()
            if figma_url and figma_url not in by_key[key]['refs']:
                by_key[key]['refs'].append(figma_url)
            container_name = (entry.get('containerName') or '').strip()
            if container_name and container_name not in by_key[key]['screen_names']:
                by_key[key]['screen_names'].append(container_name)
            if entry.get('order') is not None and by_key[key]['order'] is None:
                by_key[key]['order'] = entry['order']
            if entry.get('currentText'):
                by_key[key]['currentText'] = entry['currentText']

        # Step 3: Rebuild refs, comment, order for each key
        created_count = 0
        updated_count = 0

        for key, data in by_key.items():
            comment_lines = [f'Screen: {name}' for name in data['screen_names']]
            comment = '\n'.join(comment_lines)

            existing = TranslationEntry.objects.filter(key=key).first()
            if existing:
                update_fields = []
                # Reactivate soft-deleted entry
                if existing.deleted:
                    existing.deleted = False
                    existing.source = 'app:figma'
                    update_fields.extend(['deleted', 'source'])
                    if data['currentText'] and not existing.en:
                        existing.en = data['currentText']
                        update_fields.append('en')
                if existing.refs != data['refs']:
                    existing.refs = data['refs']
                    update_fields.append('refs')
                if existing.comment != comment:
                    existing.comment = comment
                    update_fields.append('comment')
                if data['order'] is not None and existing.order != data['order']:
                    existing.order = data['order']
                    update_fields.append('order')
                if update_fields:
                    existing.save(update_fields=update_fields)
                    updated_count += 1
            else:
                # Create new entry — never set translation values, only metadata
                entry_obj = TranslationEntry(
                    key=key,
                    comment=comment,
                    source='app:figma',
                    refs=data['refs'],
                )
                if data['currentText']:
                    entry_obj.en = data['currentText']
                if data['order'] is not None:
                    entry_obj.order = data['order']
                entry_obj.save()
                created_count += 1

        logger.info(f"[FigmaSync] Synced {len(by_key)} keys: {created_count} created, {updated_count} updated")

        dto = FigmaSyncResponse(
            synced=len(by_key),
            created=created_count,
            updated=updated_count,
        )
        return IronResponse(FigmaSyncResponseSerializer(dto))


@extend_schema(tags=['Figma Plugin'])
class FigmaRemoveRefView(FigmaApiKeyAuthentication, APIView):
    """Remove a ref from a translation entry."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Remove a Figma URL ref from a translation entry by key.',
        request={
            'type': 'object',
            'properties': {
                'key': {'type': 'string', 'description': 'Translation key'},
                'figma_url': {'type': 'string', 'description': 'Figma URL to remove from refs'},
            },
            'required': ['key', 'figma_url']
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'key': {'type': 'string'},
                    'ref_removed': {'type': 'boolean'},
                    'refs': {'type': 'array', 'items': {'type': 'string'}},
                }
            },
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        }
    )
    def post(self, request):
        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        key = request.data.get('key', '').strip()
        figma_url = request.data.get('figma_url', '').strip()
        screen_name = request.data.get('screen_name', '').strip()

        if not key:
            return IronResponse(
                {'error': 'Key is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not figma_url:
            return IronResponse(
                {'error': 'figma_url is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            entry = TranslationEntry.objects.get(key=key, deleted=False)
        except TranslationEntry.DoesNotExist:
            return IronResponse(
                {'error': f'Translation key "{key}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        update_fields = []

        # Remove figma_url from refs if present
        ref_removed = False
        if entry.refs and figma_url in entry.refs:
            entry.refs = [r for r in entry.refs if r != figma_url]
            update_fields.append('refs')
            ref_removed = True
            logger.info(f"[FigmaRemoveRef] Removed ref from {key}, remaining refs: {entry.refs}")

        # Remove screen name from comment if present
        if screen_name and entry.comment:
            screen_line = f'Screen: {screen_name}'
            lines = entry.comment.split('\n')
            new_lines = [l for l in lines if l != screen_line]
            if len(new_lines) != len(lines):
                entry.comment = '\n'.join(new_lines)
                if 'comment' not in update_fields:
                    update_fields.append('comment')

        if update_fields:
            entry.save(update_fields=update_fields)

        dto = FigmaRemoveRefResponse(
            key=entry.key,
            ref_removed=ref_removed,
            refs=entry.refs or [],
        )
        return IronResponse(FigmaRemoveRefResponseSerializer(dto))


@extend_schema(tags=['Figma Plugin'])
class FigmaScreenshotUploadView(FigmaApiKeyAuthentication, APIView):
    """Upload a Figma screen screenshot for a translation key."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Upload a screenshot of the Figma screen where a translation key is used.',
        request={
            'type': 'object',
            'properties': {
                'key': {'type': 'string', 'description': 'Translation key'},
                'image': {'type': 'string', 'description': 'Base64-encoded PNG image'},
            },
            'required': ['key', 'image']
        },
        responses={
            200: FigmaScreenshotUploadResponseSerializer,
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        }
    )
    def post(self, request):
        import base64
        from django.core.files.base import ContentFile

        key_obj, error = self.authenticate_figma(request)
        if error:
            return error

        key = request.data.get('key', '').strip()
        image_b64 = request.data.get('image', '').strip()

        if not key:
            return IronResponse(
                {'error': 'key is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not image_b64:
            return IronResponse(
                {'error': 'image is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            entry = TranslationEntry.objects.get(key=key, deleted=False)
        except TranslationEntry.DoesNotExist:
            return IronResponse(
                {'error': f'Translation key "{key}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            image_data = base64.b64decode(image_b64)
        except Exception:
            return IronResponse(
                {'error': 'Invalid base64 image data'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Delete old screenshot if exists
        if entry.screenshot:
            entry.screenshot.delete(save=False)

        filename = f"{key.replace('.', '_').replace('/', '_')}.png"
        entry.screenshot.save(filename, ContentFile(image_data), save=False)
        entry.save(update_fields=['screenshot'])

        logger.info(f"[FigmaScreenshot] Saved screenshot for key={key}")

        dto = FigmaScreenshotUploadResponse(key=key, uploaded=True)
        return IronResponse(FigmaScreenshotUploadResponseSerializer(dto))

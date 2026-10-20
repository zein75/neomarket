'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import {
  SellerApiError,
  sellerApiRequest,
  sellerArray,
  sellerBoolean,
  sellerInteger,
  sellerObject,
  sellerOptionalNullableString,
  sellerString,
} from './lib/seller-api';

import { type FormEvent, useEffect, useState } from 'react';

type CategoryAttribute = { key: string; label: string; required: boolean; value_type: 'text' | 'number' | 'select'; options: string[]; allowed_units: string[] };
type Category = { id: string; name: string; parent_id?: string | null; attribute_schema?: CategoryAttribute[]; revision?: number };
type DraftVariantForm = {
  key: string;
  sellerArticle: string;
  name: string;
  price: string;
  onHand: string;
  options: string;
};
type DraftResponse = {
  id: string;
  status: string;
  variants: Array<{ id: string }>;
};
type LocalProductDraft = {
  version: 1;
  tenantId: string;
  draftId?: string;
  draftRevision?: number;
  mutationId: string;
  stage: 'INITIAL_PRODUCT_FORM';
  updatedAt: string;
  title: string;
  description: string;
  categoryId: string;
  attributes: Record<string, string>;
  currency: string;
  variants: DraftVariantForm[];
  mediaNames: string[];
};

type DraftAutosaveResponse = {
  id: string;
  revision: number;
  payload: LocalProductDraft;
};

function decodeCategoryAttribute(value: unknown): CategoryAttribute {
  const item = sellerObject(value, 'category attribute');
  const valueType = sellerString(item.value_type, 'category attribute.value_type');
  if (valueType !== 'text' && valueType !== 'number' && valueType !== 'select') throw new TypeError('category attribute.value_type is invalid');
  return {
    key: sellerString(item.key, 'category attribute.key'),
    label: sellerString(item.label, 'category attribute.label'),
    required: sellerBoolean(item.required, 'category attribute.required'),
    value_type: valueType,
    options: sellerArray(item.options, 'category attribute.options', (option) => sellerString(option, 'option')),
    allowed_units: sellerArray(item.allowed_units, 'category attribute.allowed_units', (unit) => sellerString(unit, 'unit')),
  };
}

function decodeCategory(value: unknown): Category {
  const item = sellerObject(value, 'category');
  const schema = item.attribute_schema;
  const revision = item.revision;
  return {
    id: sellerString(item.id, 'category.id'),
    name: sellerString(item.name, 'category.name'),
    ...(item.parent_id === undefined ? {} : { parent_id: item.parent_id === null ? null : sellerString(item.parent_id, 'category.parent_id') }),
    ...(schema === undefined ? {} : { attribute_schema: sellerArray(schema, 'category.attribute_schema', decodeCategoryAttribute) }),
    ...(revision === undefined ? {} : { revision: sellerInteger(revision, 'category.revision') }),
  };
}

function decodeMediaStatus(value: unknown): { id: string; state: string; error_code?: string | null } {
  const item = sellerObject(value, 'media status');
  const errorCode = sellerOptionalNullableString(item.error_code, 'media status.error_code');
  return {
    id: sellerString(item.id, 'media status.id'),
    state: sellerString(item.state, 'media status.state'),
    ...(errorCode === undefined ? {} : { error_code: errorCode }),
  };
}

function decodeDraftResponse(value: unknown): DraftResponse {
  const item = sellerObject(value, 'product draft');
  const status = sellerString(item.status, 'product draft.status');
  if (status !== 'DRAFT') throw new TypeError('product draft.status is invalid');
  return {
    id: sellerString(item.id, 'product draft.id'),
    status,
    variants: sellerArray(item.variants, 'product draft.variants', (variant) => ({ id: sellerString(sellerObject(variant, 'product draft variant').id, 'product draft variant.id') })),
  };
}

function decodeDraftAutosave(value: unknown): DraftAutosaveResponse {
  const item = sellerObject(value, 'draft autosave');
  const payload = sellerObject(item.payload, 'draft autosave.payload');
  const variants = sellerArray(payload.variants, 'draft autosave.payload.variants', (variant) => {
    const row = sellerObject(variant, 'draft autosave variant');
    return {
      key: sellerString(row.key, 'draft autosave variant.key'),
      sellerArticle: sellerString(row.seller_article, 'draft autosave variant.seller_article'),
      name: sellerString(row.name, 'draft autosave variant.name'),
      price: sellerString(row.price, 'draft autosave variant.price'),
      onHand: sellerString(row.on_hand, 'draft autosave variant.on_hand'),
      options: sellerString(row.options, 'draft autosave variant.options'),
    };
  });
  const attributes = sellerObject(payload.attributes, 'draft autosave.payload.attributes');
  return {
    id: sellerString(item.id, 'draft autosave.id'),
    revision: sellerInteger(item.revision, 'draft autosave.revision'),
    payload: {
      version: 1,
      tenantId: '',
      mutationId: '',
      stage: 'INITIAL_PRODUCT_FORM',
      updatedAt: sellerString(item.updated_at, 'draft autosave.updated_at'),
      title: sellerString(payload.title, 'draft autosave.payload.title'),
      description: sellerString(payload.description, 'draft autosave.payload.description'),
      categoryId: payload.category_id === null ? '' : sellerString(payload.category_id, 'draft autosave.payload.category_id'),
      attributes: Object.fromEntries(Object.entries(attributes).map(([key, value]) => [key, sellerString(value, `draft autosave.payload.attributes.${key}`)])),
      currency: sellerString(payload.currency, 'draft autosave.payload.currency'),
      variants,
      mediaNames: sellerArray(payload.media_names, 'draft autosave.payload.media_names', (name) => sellerString(name, 'draft autosave media name')),
    },
  };
}

const emptyVariant = (key: string): DraftVariantForm => ({
  key,
  sellerArticle: '',
  name: '',
  price: '',
  onHand: '0',
  options: '{}',
});

export function ProductCreatePage() {
  const [pending, setPending] = useState(false);
  const [mediaProgress, setMediaProgress] = useState<{ file: string; phase: 'uploading' | 'scanning' | 'ready' | 'rejected'; percent: number } | null>(null);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<DraftResponse | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryError, setCategoryError] = useState('');
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [categoryRetryKey, setCategoryRetryKey] = useState(0);
  const [categoryId, setCategoryId] = useState('');
  const [attributes, setAttributes] = useState<Record<string, string>>({});
  const [currency, setCurrency] = useState('RUB');
  const [variants, setVariants] = useState([emptyVariant('variant-1')]);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [draftReady, setDraftReady] = useState(false);
  const [draftId, setDraftId] = useState('');
  const [draftRevision, setDraftRevision] = useState(0);
  const [draftMutationId, setDraftMutationId] = useState('');
  const [draftSaveStatus, setDraftSaveStatus] = useState('');
  const [restoredMediaNames, setRestoredMediaNames] = useState<string[]>([]);
  const [mediaNames, setMediaNames] = useState<string[]>([]);

  const hasDraftInput = Boolean(
    title.trim() || description.trim() || categoryId || Object.values(attributes).some((value) => value.trim())
      || variants.some((variant) => variant.sellerArticle || variant.name || variant.price || variant.options !== '{}')
      || mediaNames.length,
  );

  useEffect(() => {
    const controller = new AbortController();
    sellerApiRequest('/api/seller/auth/organizations', { credentials: 'include', cache: 'no-store', signal: controller.signal }, (value) =>
      sellerArray(value, 'organizations', (row) => {
        const organization = sellerObject(row, 'organization');
        return { id: sellerString(organization.id, 'organization.id'), current: sellerBoolean(organization.current, 'organization.current') };
      }),
    )
      .then((rows) => {
        setTenantId(rows.find((row) => row.current)?.id ?? '');
      })
      .catch(() => {
        if (!controller.signal.aborted) setDraftSaveStatus('Local draft recovery is unavailable without an active organization.');
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!tenantId) return;
    const storageKey = `neomarket.seller.new-product-draft.v1.${tenantId}`;
    const pointerKey = `neomarket.seller.new-product-draft-id.v1.${tenantId}`;
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      const pointer = window.localStorage.getItem(pointerKey);
      if (pointer && /^[0-9a-f-]{36}$/i.test(pointer)) setDraftId(pointer);
      if (raw) {
        const draft = JSON.parse(raw) as Partial<LocalProductDraft>;
        if (draft.version === 1 && draft.tenantId === tenantId && typeof draft.mutationId === 'string'
          && typeof draft.title === 'string' && typeof draft.description === 'string'
          && typeof draft.categoryId === 'string' && typeof draft.currency === 'string'
          && draft.stage === 'INITIAL_PRODUCT_FORM' && typeof draft.updatedAt === 'string'
          && draft.attributes && typeof draft.attributes === 'object' && !Array.isArray(draft.attributes)
          && Object.values(draft.attributes).every((value) => typeof value === 'string')
          && Array.isArray(draft.variants) && draft.variants.length > 0 && draft.variants.length <= 100
          && draft.variants.every((variant) => variant && typeof variant.key === 'string'
            && typeof variant.sellerArticle === 'string' && typeof variant.name === 'string'
            && typeof variant.price === 'string' && typeof variant.onHand === 'string'
            && typeof variant.options === 'string')
          && Array.isArray(draft.mediaNames) && draft.mediaNames.every((name) => typeof name === 'string')) {
          setTitle(draft.title);
          setDescription(draft.description);
          setCategoryId(draft.categoryId);
          setAttributes(draft.attributes as Record<string, string>);
          setCurrency(draft.currency);
          setVariants(draft.variants);
          if (typeof draft.draftId === 'string' && /^[0-9a-f-]{36}$/i.test(draft.draftId)) setDraftId(draft.draftId);
          if (typeof draft.draftRevision === 'number' && Number.isSafeInteger(draft.draftRevision) && draft.draftRevision > 0) setDraftRevision(draft.draftRevision);
          setDraftMutationId(draft.mutationId);
          setRestoredMediaNames(draft.mediaNames);
          setDraftSaveStatus('Local draft restored from this tab.');
        } else {
          window.sessionStorage.removeItem(storageKey);
        }
      }
    } catch {
      setDraftSaveStatus('Local draft recovery is unavailable.');
    } finally {
      setDraftReady(true);
    }
  }, [tenantId]);

  useEffect(() => {
    if (!tenantId || !draftReady) return;
    const storageKey = `neomarket.seller.new-product-draft.v1.${tenantId}`;
    const pointerKey = `neomarket.seller.new-product-draft-id.v1.${tenantId}`;
    let mutationId = draftMutationId;
    let serverDraftId = draftId;
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      const draft = raw ? JSON.parse(raw) as Partial<LocalProductDraft> : null;
      mutationId = typeof draft?.mutationId === 'string' ? draft.mutationId : '';
      serverDraftId = typeof draft?.draftId === 'string' ? draft.draftId : (window.localStorage.getItem(pointerKey) ?? draftId);
    } catch {
      serverDraftId = draftId;
    }
    const mutationIdValid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(mutationId);
    const serverDraftIdValid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(serverDraftId);
    if (!mutationIdValid && !serverDraftIdValid) return;
    const controller = new AbortController();
    const operationRecovery = mutationIdValid
      ? sellerApiRequest(`/api/seller/v1/products/drafts/${mutationId}`, { credentials: 'include', cache: 'no-store', signal: controller.signal }, decodeDraftResponse)
      : Promise.reject(new SellerApiError('No atomic operation key', 404, 'DRAFT_OPERATION_NOT_FOUND'));
    operationRecovery
      .then((draft) => {
        setCreated(draft);
        setDraftSaveStatus('Draft restored from the server after the create response was lost.');
        try { window.sessionStorage.removeItem(storageKey); window.localStorage.removeItem(pointerKey); } catch { /* best effort cleanup */ }
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        if (!(cause instanceof SellerApiError && cause.status === 404) || !serverDraftIdValid) {
          if (!(cause instanceof SellerApiError && cause.status === 404)) setDraftSaveStatus('Server draft recovery is unavailable; local copy retained.');
          return;
        }
        sellerApiRequest(`/api/seller/v1/products/draft-sessions/${serverDraftId}`, { credentials: 'include', cache: 'no-store', signal: controller.signal }, decodeDraftAutosave)
          .then((saved) => {
            const payload = saved.payload;
            setDraftId(saved.id);
            setDraftRevision(saved.revision);
            setTitle(payload.title);
            setDescription(payload.description);
            setCategoryId(payload.categoryId);
            setAttributes(payload.attributes);
            setCurrency(payload.currency);
            setVariants(payload.variants);
            setMediaNames([]);
            setRestoredMediaNames(payload.mediaNames);
            setDraftSaveStatus('Draft restored from the server.');
          })
          .catch((autosaveCause: unknown) => {
            if (controller.signal.aborted || (autosaveCause instanceof SellerApiError && autosaveCause.status === 404)) return;
            setDraftSaveStatus('Server draft recovery is unavailable; local copy retained.');
          });
      });
    return () => controller.abort();
  }, [draftReady, tenantId]);

  useEffect(() => {
    if (!tenantId || !draftReady || pending || created) return;
    const storageKey = `neomarket.seller.new-product-draft.v1.${tenantId}`;
    const pointerKey = `neomarket.seller.new-product-draft-id.v1.${tenantId}`;
    if (!hasDraftInput) {
      const existingDraftId = draftId;
      try {
        window.sessionStorage.removeItem(storageKey);
        window.localStorage.removeItem(pointerKey);
      } catch {
        setDraftSaveStatus('Could not clear the local draft.');
        return;
      }
      if (/^[0-9a-f-]{36}$/i.test(existingDraftId)) {
        void sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, (value) => sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'))
          .then((csrfToken) => sellerApiRequest(`/api/seller/v1/products/draft-sessions/${existingDraftId}`, { method: 'DELETE', credentials: 'include', headers: { 'X-CSRF-Token': csrfToken }, cache: 'no-store' }, () => undefined))
          .catch(() => undefined);
      }
      setDraftId('');
      setDraftRevision(0);
      setDraftSaveStatus('');
      return;
    }
    setDraftSaveStatus('Saving draft on the server…');
    const timeout = window.setTimeout(() => {
      const mutationId = draftMutationId || crypto.randomUUID();
      const serverId = draftId || crypto.randomUUID();
      const draft: LocalProductDraft = {
        version: 1,
        tenantId,
        draftId: serverId,
        draftRevision,
        mutationId,
        stage: 'INITIAL_PRODUCT_FORM',
        updatedAt: new Date().toISOString(),
        title,
        description,
        categoryId,
        attributes,
        currency,
        variants,
        mediaNames,
      };
      try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(draft));
        window.localStorage.setItem(pointerKey, serverId);
        if (!draftMutationId) setDraftMutationId(mutationId);
        if (!draftId) setDraftId(serverId);
        setRestoredMediaNames(mediaNames);
      } catch {
        setDraftSaveStatus('Server autosave is unavailable; local copy retained.');
        return;
      }
      void sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, (value) => sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'))
        .then((csrfToken) => sellerApiRequest(`/api/seller/v1/products/draft-sessions/${serverId}`, {
          method: 'PUT',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, ...(draftRevision > 0 ? { 'If-Match': String(draftRevision) } : {}) },
          body: JSON.stringify({ title, description, category_id: categoryId || null, attributes, currency, variants: variants.map((variant) => ({ key: variant.key, seller_article: variant.sellerArticle, name: variant.name, price: variant.price, on_hand: variant.onHand, options: variant.options })), media_names: mediaNames }),
          cache: 'no-store',
        }, decodeDraftAutosave))
        .then((saved) => {
          setDraftRevision(saved.revision);
          setDraftSaveStatus('Draft saved on the server.');
        })
        .catch((cause: unknown) => {
          if (cause instanceof SellerApiError && cause.status === 412) setDraftSaveStatus('Draft changed in another tab; local copy retained.');
          else setDraftSaveStatus('Server autosave is unavailable; local copy retained.');
        });
    }, 900);
    return () => window.clearTimeout(timeout);
  }, [attributes, categoryId, created, currency, description, draftReady, hasDraftInput, mediaNames, pending, tenantId, title, variants]);

  useEffect(() => {
    if (!hasDraftInput || pending || created) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warnBeforeLeaving);
    return () => window.removeEventListener('beforeunload', warnBeforeLeaving);
  }, [created, hasDraftInput, pending]);

  useEffect(() => {
    const controller = new AbortController();
    setCategoriesLoading(true);
    setCategoryError('');
    sellerApiRequest('/api/seller/categories', { credentials: 'include', cache: 'no-store', signal: controller.signal }, (value) => {
      const payload = sellerObject(value, 'categories response');
      return sellerArray(payload.items, 'categories.items', decodeCategory);
    })
      .then((items) => {
        setCategories(items);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setCategoryError(sellerErrorMessage(cause, 'Не удалось загрузить категории.'));
      })
      .finally(() => {
        if (!controller.signal.aborted) setCategoriesLoading(false);
      });
    return () => controller.abort();
  }, [categoryRetryKey]);

  function updateVariant(key: string, field: keyof Omit<DraftVariantForm, 'key'>, value: string) {
    setVariants((current) => current.map((variant) => variant.key === key ? { ...variant, [field]: value } : variant));
  }

  function addVariant() {
    setVariants((current) => current.length >= 100 ? current : [...current, emptyVariant(crypto.randomUUID())]);
  }

  function removeVariant(key: string) {
    setVariants((current) => current.length <= 1 ? current : current.filter((variant) => variant.key !== key));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (tenantId && hasDraftInput) {
      try {
        const mutationId = draftMutationId || crypto.randomUUID();
        const serverId = draftId || crypto.randomUUID();
        if (!draftMutationId) setDraftMutationId(mutationId);
        if (!draftId) setDraftId(serverId);
        window.sessionStorage.setItem(`neomarket.seller.new-product-draft.v1.${tenantId}`, JSON.stringify({
          version: 1, tenantId, draftId: serverId, draftRevision, mutationId, stage: 'INITIAL_PRODUCT_FORM', updatedAt: new Date().toISOString(),
          title, description, categoryId, attributes, currency, variants, mediaNames,
        } satisfies LocalProductDraft));
        window.localStorage.setItem(`neomarket.seller.new-product-draft-id.v1.${tenantId}`, serverId);
      } catch {
        setDraftSaveStatus('Не удалось сохранить черновик в этой вкладке.');
      }
    }
    setPending(true);
    setError('');
    setMediaProgress(null);
    setCreated(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const selectedFiles = form.getAll('media').filter((value): value is File => value instanceof File && value.size > 0);

    let payload: {
      title: string;
      description: string;
      category_id: string;
      attributes: Record<string, string>;
      media_ids: string[];
      variants: Array<{ seller_article: string; name: string; price_minor: number; currency: string; on_hand: number; options: Record<string, string> }>;
    };
    try {
      payload = {
        title: String(form.get('title') || '').trim(),
        description: String(form.get('description') || '').trim(),
        category_id: categoryId,
        attributes: Object.fromEntries(Object.entries(attributes).map(([key, value]) => [key, value.trim()])),
        media_ids: [],
        variants: variants.map((variant) => {
          const options = JSON.parse(variant.options || '{}') as unknown;
          if (!options || Array.isArray(options) || typeof options !== 'object' || Object.values(options).some((value) => typeof value !== 'string')) {
            throw new Error(`Параметры варианта «${variant.sellerArticle || variant.name}» должны быть JSON-объектом строк.`);
          }
          const priceText = variant.price.trim();
          if (!/^\d+(?:\.\d{1,2})?$/.test(priceText)) {
            throw new Error(`Укажите цену варианта «${variant.sellerArticle || variant.name}» с точностью до копейки.`);
          }
          const [whole, fraction = ''] = priceText.split('.');
          const priceMinor = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
          if (!Number.isSafeInteger(priceMinor)) throw new Error('Цена варианта превышает допустимое значение.');
          return {
            seller_article: variant.sellerArticle.trim(),
            name: variant.name.trim(),
            price_minor: priceMinor,
            currency,
            on_hand: Number(variant.onHand),
            options: options as Record<string, string>,
          };
        }),
      };
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Проверьте данные вариантов.'));
      setPending(false);
      return;
    }

    let storageKey = '';
    try {
      const csrfToken = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, (value) =>
        sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'),
      );
      if (selectedFiles.length > 20) throw new Error('Можно добавить не более 20 изображений.');
      const mediaIds: string[] = [];
      for (const file of selectedFiles) {
        if (file.size > 10_000_000 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error(`${file.name}: используйте JPEG, PNG или WebP размером до 10 МБ.`);
        const bytes = await file.arrayBuffer();
        const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (byte) => byte.toString(16).padStart(2, '0')).join('');
        const intentKey = `neomarket.media.${digest}`;
        let mediaKey = window.localStorage.getItem(intentKey) || '';
        if (!/^[0-9a-f-]{36}$/i.test(mediaKey)) { mediaKey = crypto.randomUUID(); window.localStorage.setItem(intentKey, mediaKey); }
        const intent = await sellerApiRequest('/api/seller/media/uploads', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'Idempotency-Key': mediaKey }, body: JSON.stringify({ size: file.size, content_type: file.type, sha256: digest }), cache: 'no-store' }, (value) => {
          const item = sellerObject(value, 'media intent');
          return { id: sellerString(item.id, 'media intent.id'), upload_url: sellerString(item.upload_url, 'media intent.upload_url'), state: sellerString(item.state, 'media intent.state') };
        });
        let state = intent.state;
        if (state === 'UPLOAD_PENDING') {
          setMediaProgress({ file: file.name, phase: 'uploading', percent: 0 });
          const uploadResponse = await new Promise<{ ok: boolean }>((resolve, reject) => {
            const request = new XMLHttpRequest();
            request.open('PUT', intent.upload_url!);
            request.setRequestHeader('Content-Type', file.type);
            request.setRequestHeader('X-Request-ID', crypto.randomUUID());
            request.upload.onprogress = (event) => {
              if (event.lengthComputable) setMediaProgress({ file: file.name, phase: 'uploading', percent: Math.round((event.loaded / event.total) * 100) });
            };
            request.onload = () => {
              const ok = request.status >= 200 && request.status < 300;
              if (ok) setMediaProgress({ file: file.name, phase: 'uploading', percent: 100 });
              resolve({ ok });
            };
            request.onerror = () => reject(new Error(`${file.name}: upload failed.`));
            request.send(bytes);
          });
          if (!uploadResponse.ok) throw new Error(`${file.name}: загрузка не удалась.`);
          state = 'UPLOADED';
        }
        if (state === 'UPLOADED') {
          setMediaProgress({ file: file.name, phase: 'scanning', percent: 100 });
          await sellerApiRequest(`/api/seller/media/uploads/${intent.id}/complete`, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, cache: 'no-store' }, decodeMediaStatus);
        }
        if (state === 'REJECTED') setMediaProgress({ file: file.name, phase: 'rejected', percent: 100 });
        if (state === 'REJECTED') throw new Error(`${file.name}: проверка отклонила файл.`);
        for (let attempt = 0; attempt < 60 && state !== 'READY' && state !== 'REJECTED'; attempt += 1) {
          setMediaProgress({ file: file.name, phase: 'scanning', percent: 100 });
          const status = await sellerApiRequest(`/api/seller/media/uploads/${intent.id}`, { credentials: 'include', cache: 'no-store' }, decodeMediaStatus);
          state = status.state;
          if (state === 'REJECTED') setMediaProgress({ file: file.name, phase: 'rejected', percent: 100 });
          if (state === 'REJECTED') throw new Error(`${file.name}: проверка отклонила файл (${status.error_code || 'INVALID_IMAGE'}).`);
          if (state === 'UPLOAD_PENDING' || state === 'EXPIRED') throw new Error(`${file.name}: срок загрузки истёк, повторите попытку.`);
          if (state !== 'READY') await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
        if (state !== 'READY') throw new Error(`${file.name}: проверка изображения занимает слишком долго. Попробуйте сохранить черновик ещё раз.`);
        setMediaProgress({ file: file.name, phase: 'ready', percent: 100 });
        mediaIds.push(intent.id);
        window.localStorage.removeItem(intentKey);
      }
      payload.media_ids = mediaIds;
      const requestBody = JSON.stringify(payload);
      const fingerprintBytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(requestBody)));
      const fingerprint = Array.from(fingerprintBytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
      storageKey = `neomarket.product-draft.${fingerprint}`;
      let idempotencyKey = window.localStorage.getItem(storageKey) || '';
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(idempotencyKey)) {
        idempotencyKey = crypto.randomUUID();
        window.localStorage.setItem(storageKey, idempotencyKey);
      }
      const result = await sellerApiRequest('/api/seller/v1/products/drafts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey },
        body: requestBody,
      }, decodeDraftResponse);
      window.localStorage.removeItem(storageKey);
      if (tenantId) {
        window.sessionStorage.removeItem(`neomarket.seller.new-product-draft.v1.${tenantId}`);
        window.localStorage.removeItem(`neomarket.seller.new-product-draft-id.v1.${tenantId}`);
      }
      if (/^[0-9a-f-]{36}$/i.test(draftId)) {
        await sellerApiRequest(`/api/seller/v1/products/draft-sessions/${draftId}`, { method: 'DELETE', credentials: 'include', headers: { 'X-CSRF-Token': csrfToken }, cache: 'no-store' }, () => undefined).catch(() => undefined);
      }
      setCreated(result);
      formElement.reset();
      setTitle('');
      setDescription('');
      setCurrency('RUB');
      setVariants([emptyVariant(crypto.randomUUID())]);
      setAttributes({});
      setMediaNames([]);
      setRestoredMediaNames([]);
      setDraftId('');
      setDraftRevision(0);
      setDraftMutationId('');
      setDraftSaveStatus('');
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Операция не выполнена.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="seller-app" id="main-content">
      <SellerSidebar variant="catalog" activePath="/products" badge="OWNER-SCOPED API" />
      <section className="seller-content">
        <div className="private-bar"><span>SELLER / NEW PRODUCT</span><span>LOCAL DRAFT RECOVERY</span></div>
        <p className="eyebrow">SELLER HUB / SE-05</p>
        <div className="page-heading"><h1>Новый черновик</h1><a className="seller-product-link" href="/products">К товарам</a></div>
        <p className="seller-hint">Черновик сохраняет товар и все варианты одной транзакцией. Изображения добавляются после настройки безопасной загрузки медиа.</p>
        {draftSaveStatus && <p className="seller-muted" role="status" aria-live="polite">{draftSaveStatus}</p>}
        {restoredMediaNames.length > 0 && <p className="seller-state" role="status">После восстановления выберите файлы заново: {restoredMediaNames.join(', ')}</p>}
        {created && <div className="seller-state" role="status"><strong>Черновик сохранён: {created.variants.length} вариантов.</strong> <a className="seller-product-link" href={`/products/${created.id}`}>Открыть карточку</a></div>}
        {error && <div className="seller-state seller-error" role="alert">{error}</div>}
        {mediaProgress && <div className="seller-state" role="status" aria-live="polite">
          <strong>{mediaProgress.file}</strong>: {mediaProgress.phase === 'uploading' ? `Uploading ${mediaProgress.percent}%` : mediaProgress.phase === 'scanning' ? 'Security scan in progress' : mediaProgress.phase === 'rejected' ? 'Security scan rejected this file' : 'File verified'}
          {mediaProgress.phase === 'uploading' && <progress aria-label={`Upload progress for ${mediaProgress.file}`} max={100} value={mediaProgress.percent} />}
        </div>}
        {categoryError && <div className="seller-state seller-error" role="alert"><strong>{categoryError}</strong><button className="seller-product-link" type="button" onClick={() => setCategoryRetryKey((current) => current + 1)}>Повторить</button></div>}
        {!categoriesLoading && !categoryError && categories.length === 0 && <p className="seller-state" role="status">Активные категории не настроены. Создание товара временно недоступно.</p>}
        <form className="seller-form" onSubmit={submit}>
          <label>Название<input name="title" value={title} onChange={(event) => setTitle(event.target.value)} required minLength={1} maxLength={255} /></label>
          <label>Описание<textarea name="description" value={description} onChange={(event) => setDescription(event.target.value)} required minLength={1} maxLength={20000} rows={4} /></label>
          <label>Изображения (JPEG, PNG, WebP; до 20 файлов по 10 МБ)<input type="file" name="media" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => { setMediaNames(Array.from(event.target.files ?? []).map((file) => file.name)); setRestoredMediaNames([]); }} /></label>
          <label>Category<select name="categoryId" required value={categoryId} onChange={(event) => {
            const nextCategoryId = event.target.value;
            if (Object.values(attributes).some((value) => value.trim()) && !window.confirm('Changing category clears the current attributes. Continue?')) return;
            setCategoryId(nextCategoryId);
            setAttributes({});
          }} disabled={!categories.length || Boolean(categoryError)}><option value="" disabled>{categoriesLoading ? 'Loading categories…' : 'Choose a category'}</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.parent_id ? `— ${category.name}` : category.name}</option>)}</select></label>
          {categories.find((category) => category.id === categoryId)?.attribute_schema?.length ? <fieldset className="seller-form">
            <legend>Required product attributes</legend>
            {categories.find((category) => category.id === categoryId)?.attribute_schema?.map((attribute) => <label key={attribute.key}>{attribute.label}{attribute.required ? ' *' : ''}
              {attribute.value_type === 'select' ? <select name={`attribute-${attribute.key}`} required={attribute.required} value={attributes[attribute.key] ?? ''} onChange={(event) => setAttributes((current) => ({ ...current, [attribute.key]: event.target.value }))}>
                <option value="">Choose a value</option>{attribute.options.map((option) => <option key={option} value={option}>{option}</option>)}
              </select> : <input name={`attribute-${attribute.key}`} type={attribute.value_type === 'number' ? 'number' : 'text'} required={attribute.required} value={attributes[attribute.key] ?? ''} onChange={(event) => setAttributes((current) => ({ ...current, [attribute.key]: event.target.value }))} />}
              {attribute.allowed_units.length > 0 && <span className="seller-muted">{attribute.allowed_units.join(', ')}</span>}
            </label>)}
          </fieldset> : null}
          <label>Валюта вариантов<input name="currency" required pattern="[A-Z]{3}" minLength={3} maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></label>
          <div className="seller-section">
            <div className="section-head"><h2>Варианты SKU ({variants.length}/100)</h2><button className="seller-product-link" type="button" onClick={addVariant} disabled={variants.length >= 100}>Добавить вариант</button></div>
            {variants.map((variant, index) => (
              <fieldset className="seller-form" key={variant.key}>
                <legend>Вариант {index + 1}</legend>
                <label>Артикул продавца<input value={variant.sellerArticle} onChange={(event) => updateVariant(variant.key, 'sellerArticle', event.target.value)} required maxLength={128} /></label>
                <label>Название SKU<input value={variant.name} onChange={(event) => updateVariant(variant.key, 'name', event.target.value)} required maxLength={255} /></label>
                <label>Цена<input type="number" value={variant.price} onChange={(event) => updateVariant(variant.key, 'price', event.target.value)} required min={0} step="0.01" /></label>
                <label>Остаток<input type="number" value={variant.onHand} onChange={(event) => updateVariant(variant.key, 'onHand', event.target.value)} required min={0} step={1} /></label>
                <label>Параметры варианта (JSON)<textarea value={variant.options} onChange={(event) => updateVariant(variant.key, 'options', event.target.value)} rows={2} /></label>
                <button className="seller-product-link" type="button" onClick={() => removeVariant(variant.key)} disabled={variants.length <= 1}>Удалить вариант</button>
              </fieldset>
            ))}
          </div>
          <button className="seller-submit" type="submit" disabled={pending || categoriesLoading || !categories.length || Boolean(categoryError)}>{pending ? 'Сохраняем…' : 'Сохранить черновик'}</button>
        </form>
      </section>
    </main>
  );
}

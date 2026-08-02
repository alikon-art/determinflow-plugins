"""Exact PostgreSQL constraints required by Novel API migrations."""

CONSTRAINT_SIGNATURES = {'20260601_novel_api_baseline': (('book', 'p', 'PRIMARY KEY (id)'),
                                 ('chapter',
                                  'f',
                                  'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                                  'CASCADE'),
                                 ('chapter', 'p', 'PRIMARY KEY (id)'),
                                 ('chapter', 'u', 'UNIQUE (book_id, chapter_number)'),
                                 ('character',
                                  'f',
                                  'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                                  'CASCADE'),
                                 ('character', 'p', 'PRIMARY KEY (id)'),
                                 ('character', 'u', 'UNIQUE (book_id, name)'),
                                 ('debt',
                                  'f',
                                  'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                                  'CASCADE'),
                                 ('debt', 'p', 'PRIMARY KEY (id)'),
                                 ('debt', 'u', 'UNIQUE (book_id, item_id)'),
                                 ('hook',
                                  'f',
                                  'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                                  'CASCADE'),
                                 ('hook', 'p', 'PRIMARY KEY (id)'),
                                 ('hook', 'u', 'UNIQUE (book_id, item_id)'),
                                 ('outline',
                                  'f',
                                  'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                                  'CASCADE'),
                                 ('outline', 'p', 'PRIMARY KEY (id)'),
                                 ('outline',
                                  'u',
                                  'UNIQUE (book_id, type, volume_number)'),
                                 ('world',
                                  'f',
                                  'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                                  'CASCADE'),
                                 ('world', 'p', 'PRIMARY KEY (id)'),
                                 ('world', 'u', 'UNIQUE (book_id)')),
 '20260609_product_schema': (('novel_job',
                              'f',
                              'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                              'CASCADE'),
                             ('novel_job', 'p', 'PRIMARY KEY (id)'),
                             ('novel_job_event',
                              'f',
                              'FOREIGN KEY (job_id) REFERENCES novel_job(id) ON DELETE '
                              'CASCADE'),
                             ('novel_job_event', 'p', 'PRIMARY KEY (id)'),
                             ('novel_resource_revision',
                              'f',
                              'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                              'CASCADE'),
                             ('novel_resource_revision', 'p', 'PRIMARY KEY (id)'),
                             ('novel_resource_revision',
                              'u',
                              'UNIQUE (book_id, resource_type, resource_key, version)'),
                             ('novel_resource_state',
                              'f',
                              'FOREIGN KEY (book_id) REFERENCES book(id) ON DELETE '
                              'CASCADE'),
                             ('novel_resource_state',
                              'p',
                              'PRIMARY KEY (book_id, resource_type, resource_key)'))}
